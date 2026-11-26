# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import datetime
import json
from dataclasses import dataclass, field

import frappe
from frappe.query_builder import Order

DOCTYPE = "Usage Month"
CORRECTION = "Usage Month Correction"
LEVEL = "Level"
ESTIMATED = "Estimated"
OPEN = "Open"
CREDIT_DUE = "Credit Due"
PENDING = (OPEN, CREDIT_DUE)
BILLED = "Billed"
DAY_FIELDS = tuple(f"d{day:02d}" for day in range(1, 32))
WRITTEN = "written"
CORRECTED = "corrected"
MASKS = ("filled", "billed", "written_off", "estimated", "open_days")

_META_FIELDS = ("name", "creation", "modified", "owner", "modified_by")
_KEY_FIELDS = ("service", "subject", "meter", "dimension", "month", "subscription")
_CONTEXT_FIELDS = ("aggregation", "team", "resource_type", "unit")
_READ_FIELDS = (
	*_KEY_FIELDS,
	*_CONTEXT_FIELDS,
	"name",
	"carries_bundle",
	"slots",
	*MASKS,
	*DAY_FIELDS,
)


@dataclass
class Written:
	"""How many lines a write stored, the lines to send again, and the corrections it kept."""

	count: int = 0
	conflicts: list[dict] = field(default_factory=list)
	corrections: int = 0


def bit(day: int) -> int:
	"""The mask bit of a day of the month."""
	return 1 << (day - 1)


def month_of(on) -> datetime.date:
	return frappe.utils.getdate(on).replace(day=1)


def write_lines(rows: list[dict], report: str | None, source: str) -> Written:
	"""Write merged day lines into their month rows, under one lock for the whole batch."""
	if not rows:
		return Written()
	now = frappe.utils.now_datetime()
	try:
		_insert_missing(rows, now)
		months = _locked_months(rows)
	except frappe.QueryDeadlockError:
		# Another worker changed one of these rows after this transaction began. Under snapshot
		# isolation the lock is refused, so the whole batch is sent or read again.
		return Written(conflicts=list(rows))
	written = Written()
	for row in rows:
		month = _month_for(months, row)
		if month is None:
			written.conflicts.append(row)
			continue
		outcome = month.apply(row, report, source, now)
		written.count += outcome == WRITTEN
		written.corrections += outcome == CORRECTED
	for rows_of_key in months.values():
		for month in rows_of_key:
			month.save(now)
	return written


def stamp_days(masks: dict[str, int], invoice: str) -> None:
	"""Mark the counted days of these month rows as billed by the invoice. A billed day keeps its invoice."""
	if not masks:
		return
	now = frappe.utils.now_datetime()
	table = frappe.qb.DocType(DOCTYPE)
	for month in _locked(table.name.isin(list(masks))):
		month.stamp(masks[month.record["name"]] & ~month.record["billed"], invoice, now)
		month.save(now)


def locked_meter_months(subscription: str, resource_type: str, dimension: str, month) -> "list[MonthRow]":
	"""A meter's month rows up to `month`, locked, so a draft bills the values it read."""
	table = frappe.qb.DocType(DOCTYPE)
	return _locked(
		(table.subscription == subscription)
		& (table.resource_type == resource_type)
		& (table.dimension == dimension)
		& (table.month <= month)
	)


def insert_month(meter, month) -> None:
	"""Insert an empty row for a meter's month, to carry a month that has only late days."""
	row = {
		name: meter.get(name) for name in (*_CONTEXT_FIELDS, "service", "meter", "dimension", "subscription")
	}
	_insert_missing([{**row, "subject": meter.day_subject, "day": month}], frappe.utils.now_datetime())


def release_days(invoice: str, team: str, since) -> None:
	"""Unmark the days a cancelled invoice billed. Only rows stamped since it was made can hold one."""
	now = frappe.utils.now_datetime()
	table = frappe.qb.DocType(DOCTYPE)
	for month in _locked((table.team == team) & (table.stamped_at >= since)):
		month.release(invoice)
		month.save(now)


class MonthRow:
	"""One locked Usage Month, changed in memory and saved with one statement."""

	def __init__(self, record: dict, corrections: list):
		self.record = record
		self.slots = _slots(record.get("slots"))
		self.corrections = corrections
		self.changed_days: set[int] = set()
		self.is_changed = False
		self.stamped_at = None

	def has_day(self, day: int, mask: str = "filled") -> bool:
		return bool(frappe.utils.cint(self.record[mask]) & bit(day))

	def get_day(self, day: int) -> frappe._dict:
		"""The stored value of a day, shaped as a line."""
		slot = self.slots.get(str(day), {})
		return frappe._dict(
			quantity=frappe.utils.flt(self.record[DAY_FIELDS[day - 1]]),
			included=frappe.utils.flt(slot.get("included")),
			as_of=slot.get("as_of"),
			estimated=self.has_day(day, "estimated"),
			invoice=slot.get("invoice"),
			aggregation=self.record["aggregation"],
			report=slot.get("report"),
		)

	def get_open_days(self) -> list[frappe._dict]:
		"""The days not yet billed or written off, as the recount weighs them."""
		return [
			frappe._dict(
				month_row=self.record["name"],
				number=day,
				day=self.record["month"].replace(day=day),
				quantity=frappe.utils.flt(self.record[DAY_FIELDS[day - 1]]),
				included=frappe.utils.flt(self.slots.get(str(day), {}).get("included")),
				aggregation=self.record["aggregation"],
			)
			for day in _days_of(frappe.utils.cint(self.record["open_days"]))
		]

	def apply(self, row: dict, report: str | None, source: str, now) -> str | None:
		"""Apply one line to its day: fill it, replace it, or keep a correction of a billed day."""
		day = frappe.utils.getdate(row["day"]).day
		if not self.has_day(day):
			self._fill(day, row, report, source, now)
			return WRITTEN
		if self.has_day(day, "billed"):
			return self._correct(day, row, report)
		if not is_newer(self.get_day(day), row):
			return None
		self._replace(day, row, report, source, now)
		return WRITTEN

	def stamp(self, mask: int, invoice: str, now) -> None:
		"""Mark the days of `mask` as billed by the invoice."""
		for day in _days_of(mask):
			self.slots[str(day)]["invoice"] = invoice
		self.record["billed"] |= mask
		self.stamped_at = now
		self.is_changed = True

	def release(self, invoice: str) -> None:
		"""Unmark the days the invoice billed."""
		for day in _days_of(self.record["billed"]):
			if self.slots.get(str(day), {}).get("invoice") == invoice:
				del self.slots[str(day)]["invoice"]
				self.record["billed"] &= ~bit(day)
				self.is_changed = True

	def save(self, now) -> None:
		if not self.is_changed:
			return
		table = frappe.qb.DocType(DOCTYPE)
		record = self.record
		record["open_days"] = record["filled"] & ~record["billed"] & ~record["written_off"]
		query = frappe.qb.update(table).set(table.slots, json.dumps(self.slots, sort_keys=True))
		for name in (*MASKS, "carries_bundle", *(DAY_FIELDS[day - 1] for day in self.changed_days)):
			query = query.set(table[name], record[name])
		if self.changed_days:
			query = query.set(table.changed_at, now)
		if self.stamped_at:
			query = query.set(table.stamped_at, self.stamped_at)
		query.set(table.modified, now).where(table.name == record["name"]).run()

	def _fill(self, day: int, row: dict, report: str | None, source: str, now) -> None:
		record = self.record
		record["filled"] |= bit(day)
		if row.get("estimated"):
			record["estimated"] |= bit(day)
		if row.get("written_off"):
			record["written_off"] |= bit(day)
		self.slots[str(day)] = {}
		self._set_value(day, row, report, source)
		self._set_reading(day, row, now)

	def _replace(self, day: int, row: dict, report: str | None, source: str, now) -> None:
		current = self.get_day(day)
		if current.aggregation == LEVEL:
			# An older reading may still raise the peak, but never brings back the bundle it was read with.
			raises = current.estimated or current.quantity < frappe.utils.flt(row["quantity"])
			as_new = current.estimated or _is_as_new(row, current)
		else:
			raises = as_new = True
		if raises:
			self._set_value(day, row, report, source)
		if as_new:
			self._set_reading(day, row, now)
		self.record["estimated"] &= ~bit(day)
		self.slots[str(day)]["landed_at"] = str(now)

	def _set_value(self, day: int, row: dict, report: str | None, source: str) -> None:
		slot = self.slots[str(day)]
		self.record[DAY_FIELDS[day - 1]] = frappe.utils.flt(row["quantity"])
		slot.update(source=ESTIMATED if row.get("estimated") else source, report=report)
		_set_optional(slot, "amount", frappe.utils.flt(row.get("source_amount")))
		_set_optional(slot, "currency", row.get("source_currency"))
		self.changed_days.add(day)
		self.is_changed = True

	def _set_reading(self, day: int, row: dict, now) -> None:
		"""When the day was read and landed, and the bundle read with it."""
		slot = self.slots[str(day)]
		# A line without a bundle keeps the stored one; absent is not 0.
		if "included" in row:
			_set_optional(slot, "included", frappe.utils.flt(row["included"]))
			if frappe.utils.flt(row["included"]) > 0:
				self.record["carries_bundle"] = 1
		_set_optional(slot, "as_of", str(row["as_of"]) if row.get("as_of") else None)
		slot["landed_at"] = str(now)
		self.changed_days.add(day)
		self.is_changed = True

	def _correct(self, day: int, row: dict, report: str | None) -> str | None:
		"""Keep a later value of a billed day as a correction. The billed value never changes."""
		pending = self._correction(day, PENDING)
		current = self.get_day(day)
		effective = frappe._dict(current, invoice=None)
		if pending:
			effective.update(quantity=pending.value, as_of=pending.as_of, estimated=False)
		if not is_newer(effective, row) or frappe.utils.flt(row["quantity"]) == effective.quantity:
			return None
		billed = self._correction(day, (BILLED,))
		billed_value = billed.value if billed else current.quantity
		if pending:
			frappe.db.delete(CORRECTION, {"name": pending.name})
			self.corrections.remove(pending)
		if frappe.utils.flt(row["quantity"]) != frappe.utils.flt(billed_value):
			original = billed.report if billed else current.report
			self._add_correction(day, row, report, billed_value, original, current.invoice)
		return CORRECTED

	def _correction(self, day: int, statuses: tuple):
		"""The latest correction of a day in one of `statuses`, or None."""
		found = [c for c in self.corrections if c.day == day and c.status in statuses]
		return found[-1] if found else None

	def _add_correction(self, day: int, row: dict, report, billed_value: float, original, invoice) -> None:
		# The dispute window runs from the invoice that billed the day, whichever invoice bills the correction.
		billed_on = frappe.db.get_value("Invoice", invoice, "creation")
		correction = frappe.get_doc(
			{
				"doctype": CORRECTION,
				"parent": self.record["name"],
				"parenttype": DOCTYPE,
				"parentfield": "corrections",
				"idx": len(self.corrections) + 1,
				"day": day,
				"billed_value": billed_value,
				"value": frappe.utils.flt(row["quantity"]),
				"original_report": original,
				"report": report,
				"as_of": row.get("as_of"),
				"billed_invoice_date": frappe.utils.getdate(billed_on) if billed_on else None,
				# Higher or lower, the next draft rates it: only a value that lowers the bill is Credit Due.
				"status": OPEN,
			}
		)
		correction.db_insert()
		self.corrections.append(frappe._dict(correction.as_dict()))


def is_newer(current, row: dict) -> bool:
	"""Whether `row` should replace the stored day `current`."""
	if current.get("invoice") or row.get("estimated"):
		return False
	if current.get("estimated"):
		return True
	if current.get("aggregation") == LEVEL:
		return _is_higher(row, current) or _is_rebundled(row, current)
	return frappe.utils.get_datetime(row["as_of"]) > frappe.utils.get_datetime(current.get("as_of"))


def _is_higher(row: dict, current) -> bool:
	return frappe.utils.flt(row["quantity"]) > frappe.utils.flt(current.get("quantity"))


def _is_rebundled(row: dict, current) -> bool:
	"""Whether a reading no older than the day's last one says the plan's bundle changed, as a resize does."""
	if "included" not in row:
		return False
	if frappe.utils.flt(row["included"]) == frappe.utils.flt(current.get("included")):
		return False
	return _is_as_new(row, current)


def _is_as_new(row: dict, current) -> bool:
	"""Whether `row` was read no earlier than the stored day's last reading."""
	if not current.get("as_of"):
		return True
	return frappe.utils.get_datetime(row["as_of"]) >= frappe.utils.get_datetime(current.get("as_of"))


def day_rows(filters: dict, day=None) -> list[frappe._dict]:
	"""The filled days of the month rows that match `filters`, one dict per day, oldest first."""
	# A row past retention keeps no day values.
	filters = {"pruned": 0, **filters}
	if day:
		filters = {**filters, "month": month_of(day)}
	months = frappe.get_all(DOCTYPE, filters=filters, fields=list(_READ_FIELDS), order_by="month asc")
	days = [_day_row(month, number) for month in months for number in _filled_days(month)]
	if day:
		days = [row for row in days if row.day == frappe.utils.getdate(day)]
	return sorted(days, key=lambda row: (row.day, row.dimension, row.subject))


def subjects_with_day(service: str, day) -> set[str]:
	"""The subjects of a service that have a value for a UTC day."""
	table = frappe.qb.DocType(DOCTYPE)
	day = frappe.utils.getdate(day)
	return set(
		(
			frappe.qb.from_(table)
			.select(table.subject)
			.distinct()
			.where(
				(table.service == service)
				& (table.month == month_of(day))
				& (table.filled.bitwiseand(bit(day.day)) != 0)
			)
		).run(pluck=True)
	)


def _day_row(month, day: int) -> frappe._dict:
	slot = _slots(month.slots).get(str(day), {})
	return frappe._dict(
		{key: month[key] for key in (*_KEY_FIELDS, *_CONTEXT_FIELDS)},
		month_row=month.name,
		day=month.month.replace(day=day),
		quantity=frappe.utils.flt(month[DAY_FIELDS[day - 1]]),
		included=frappe.utils.flt(slot.get("included")),
		estimated=int(bool(month.estimated & bit(day))),
		written_off=int(bool(month.written_off & bit(day))),
		invoice=slot.get("invoice"),
		as_of=frappe.utils.get_datetime(slot["as_of"]) if slot.get("as_of") else None,
		landed_at=frappe.utils.get_datetime(slot["landed_at"]) if slot.get("landed_at") else None,
		source=slot.get("source"),
		report=slot.get("report"),
		source_amount=frappe.utils.flt(slot.get("amount")),
		source_currency=slot.get("currency"),
	)


def _filled_days(month) -> list[int]:
	return _days_of(frappe.utils.cint(month.filled))


def _days_of(mask: int) -> list[int]:
	"""The days whose bit is set in `mask`."""
	return [day for day in range(1, 32) if mask & bit(day)]


def _slots(value) -> dict:
	if isinstance(value, dict):
		return value
	return json.loads(value) if value else {}


def _set_optional(slot: dict, key: str, value) -> None:
	"""Keep a slot small: an empty value is left out."""
	if value:
		slot[key] = value
	else:
		slot.pop(key, None)


def _key(row) -> tuple:
	return (
		row["service"],
		row["subject"],
		row["meter"],
		row.get("dimension") or "",
		month_of(row.get("day") or row.get("month")),
	)


def _month_for(months: dict, row: dict) -> MonthRow | None:
	"""The row that holds the line's day, else the row of the line's subscription."""
	candidates = months.get(_key(row), [])
	day = frappe.utils.getdate(row["day"]).day
	for month in candidates:
		if month.has_day(day):
			return month
	# A row inserted by a worker that committed after this transaction began is not seen.
	return next((month for month in candidates if month.record["subscription"] == row["subscription"]), None)


def _insert_missing(rows: list[dict], now) -> None:
	"""Insert an empty month row for each line's month and subscription that has none."""
	user = frappe.session.user
	keys = {(*_key(row), row["subscription"]): row for row in rows}
	values = [
		(
			frappe.generate_hash(length=12),
			now,
			now,
			user,
			user,
			*key,
			*(row.get(name) for name in _CONTEXT_FIELDS),
		)
		for key, row in keys.items()
	]
	frappe.db.bulk_insert(
		DOCTYPE,
		[*_META_FIELDS, *_KEY_FIELDS, *_CONTEXT_FIELDS],
		values,
		ignore_duplicates=True,
	)


def _locked_months(rows: list[dict]) -> dict[tuple, list[MonthRow]]:
	"""The month rows of these lines, by month key."""
	table = frappe.qb.DocType(DOCTYPE)
	found = _locked(
		table.service.isin(list({row["service"] for row in rows}))
		& table.subject.isin(list({row["subject"] for row in rows}))
		& table.month.isin(list({month_of(row["day"]) for row in rows})),
		with_corrections=True,
	)
	months: dict[tuple, list[MonthRow]] = {}
	for month in found:
		months.setdefault(_key(month.record), []).append(month)
	return months


def _locked(condition, with_corrections: bool = False) -> list[MonthRow]:
	"""The month rows that match, locked in name order so two writers never deadlock."""
	table = frappe.qb.DocType(DOCTYPE)
	found = (
		frappe.qb.from_(table)
		.select(*(table[name] for name in _READ_FIELDS))
		.where(condition)
		.orderby(table.name, order=Order.asc)
		.for_update()
	).run(as_dict=True)
	billed = [month.name for month in found if month.billed] if with_corrections else []
	corrections = _corrections_of(billed)
	return [MonthRow(month, corrections.get(month.name, [])) for month in found]


def _corrections_of(names: list[str]) -> dict[str, list]:
	if not names:
		return {}
	rows = frappe.get_all(
		CORRECTION,
		filters={"parent": ["in", names], "parenttype": DOCTYPE},
		fields=["name", "parent", "day", "value", "as_of", "status", "report"],
		order_by="idx asc",
	)
	by_parent: dict[str, list] = {}
	for row in rows:
		by_parent.setdefault(row.parent, []).append(row)
	return by_parent
