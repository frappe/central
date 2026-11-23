# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import datetime
from dataclasses import dataclass, field

import frappe
from frappe.query_builder import Criterion

DOCTYPE = "Usage Day"
LEVEL = "Level"
KEPT_MONTHS = 13
# A UTC day is estimated only after the day has ended and late lines have had 48 hours.
ESTIMATE_AFTER_DAYS = 3
ESTIMATE_LOOKBACK_DAYS = 7
DELETE_PAGE = 5000

_META_FIELDS = ("name", "creation", "modified", "owner", "modified_by")
# A line's own values, in the order they are inserted.
_DAY_FIELDS = (
	"service",
	"meter",
	"subject",
	"dimension",
	"day",
	"aggregation",
	"team",
	"subscription",
	"resource_type",
	"quantity",
	"included",
	"unit",
	"source_amount",
	"source_currency",
	"as_of",
	"written_off",
)
_INSERT_FIELDS = (*_META_FIELDS, *_DAY_FIELDS, "landed_at", "estimated")


@dataclass
class Written:
	"""How many lines a write stored, and the lines another worker stored first."""

	count: int = 0
	conflicts: list[dict] = field(default_factory=list)


def write_days(rows: list[dict]) -> Written:
	"""Store each line as its subject's row for its UTC day."""
	# An existing day takes a line only when it is a real reading over an estimate, a higher Level
	# peak or a newer Sum total. A billed day never changes.
	rows = _merged(rows)
	if not rows:
		return Written()
	now = frappe.utils.now_datetime()
	existing = _existing_days(rows)
	fresh = [row for row in rows if _key(row) not in existing]
	conflicts = _insert(fresh, now)
	changed = _changed(rows, existing)
	for name, row in changed:
		_update(name, row, now)
	return Written(len(fresh) - len(conflicts) + len(changed), conflicts)


def is_newer(current, row: dict) -> bool:
	"""Whether `row` should replace the stored day `current`."""
	if current.get("invoice") or row.get("estimated"):
		return False
	if current.get("estimated"):
		return True
	if current.get("aggregation") == LEVEL:
		return frappe.utils.flt(row["quantity"]) > frappe.utils.flt(current.get("quantity"))
	return frappe.utils.get_datetime(row["as_of"]) > frappe.utils.get_datetime(current.get("as_of"))


def _changed(rows: list[dict], existing: dict) -> list[tuple]:
	"""(stored day, line) for each line that should replace its stored day."""
	return [
		(existing[_key(row)].name, row)
		for row in rows
		if _key(row) in existing and is_newer(existing[_key(row)], row)
	]


def _merged(rows: list[dict]) -> list[dict]:
	"""One line per subject, meter, dimension and day: a batch may carry the same day twice."""
	kept: dict = {}
	bill_from = _bill_from({row["service"] for row in rows})
	for row in rows:
		# Float columns are NOT NULL in Frappe, so a blank amount is stored as 0. A blank dimension is
		# stored as "", not NULL, so the unique key still holds.
		row = {
			**row,
			"dimension": row.get("dimension") or "",
			"quantity": frappe.utils.flt(row.get("quantity")),
			"included": frappe.utils.flt(row.get("included")),
			"source_amount": frappe.utils.flt(row.get("source_amount")),
			"written_off": _is_before_billing(row, bill_from.get(row["service"])),
		}
		key = _key(row)
		if key not in kept or is_newer(kept[key], row):
			kept[key] = row
	return list(kept.values())


def stamp_days(names: list[str], invoice: str) -> None:
	"""Mark these unbilled days as billed by the invoice."""
	if not names:
		return
	day = frappe.qb.DocType(DOCTYPE)
	frappe.qb.update(day).set(day.invoice, invoice).where(day.name.isin(names) & day.invoice.isnull()).run()


def release_days(invoice: str) -> None:
	"""Unmark the days a cancelled invoice billed."""
	day = frappe.qb.DocType(DOCTYPE)
	frappe.qb.update(day).set(day.invoice, None).where(day.invoice == invoice).run()


def fill_missing_days(today=None) -> int:
	"""Daily: give a Level subject that went silent its last reading, marked estimated."""
	last = _utc_date(today) - datetime.timedelta(days=ESTIMATE_AFTER_DAYS)
	written = 0
	for offset in range(ESTIMATE_LOOKBACK_DAYS, -1, -1):
		written += _estimate_day(last - datetime.timedelta(days=offset))
	return written


def prune_old_days(today=None) -> int:
	"""Daily: delete billed or written-off days older than the kept months."""
	# The monthly rollup keeps a billed day's total; a written-off day was never going to bill.
	cutoff = frappe.utils.add_months(_utc_date(today).replace(day=1), -KEPT_MONTHS)
	table = frappe.qb.DocType(DOCTYPE)
	done = table.invoice.isnotnull() | (table.written_off == 1)
	deleted = 0
	while names := (
		frappe.qb.from_(table).select(table.name).where((table.day < cutoff) & done).limit(DELETE_PAGE)
	).run(pluck=True):
		frappe.qb.from_(table).delete().where(table.name.isin(names)).run()
		deleted += len(names)
	return deleted


def utc_today() -> datetime.date:
	return datetime.datetime.now(datetime.UTC).date()


def _utc_date(today) -> datetime.date:
	return frappe.utils.getdate(today) if today else utc_today()


def _estimate_day(day: datetime.date) -> int:
	"""Copy the previous day's Level rows onto `day` for live subjects that have no row on it."""
	previous = frappe.get_all(
		DOCTYPE,
		filters={"day": day - datetime.timedelta(days=1), "aggregation": LEVEL},
		fields=[*_DAY_FIELDS, "estimated"],
	)
	if not previous:
		return 0
	live = _live_subjects({row.service for row in previous})
	rows = [
		{**row, "day": day, "estimated": 1, "as_of": None, "landed_at": None}
		for row in previous
		if (row.service, row.subject) in live
	]
	return write_days(rows).count


def _live_subjects(services: set) -> set:
	"""(service, subject) of every service a team still has, suspended ones included."""
	from central.billing.revenue.bundled_buckets import billed_subjects_of

	return {(service, subject) for service in services for subject in billed_subjects_of(service)}


def _key(row) -> tuple:
	day = str(frappe.utils.getdate(row["day"]))
	return (row["service"], row["subject"], row["meter"], row.get("dimension") or "", day)


def _bill_from(services: set) -> dict:
	"""The first billed day of each service that starts billing later than its usage."""
	rows = frappe.get_all(
		"Service",
		filters={"name": ["in", list(services)], "bill_from": ["is", "set"]},
		fields=["name", "bill_from"],
	)
	return {row.name: row.bill_from for row in rows}


def _is_before_billing(row: dict, bill_from) -> int:
	return int(bool(bill_from) and frappe.utils.getdate(row["day"]) < frappe.utils.getdate(bill_from))


def _existing_days(rows: list[dict]) -> dict:
	"""The stored days for these lines, by key. One query for the whole batch."""
	day = frappe.qb.DocType(DOCTYPE)
	return _days_where(
		Criterion.all(
			[
				day.service.isin(list({row["service"] for row in rows})),
				day.subject.isin(list({row["subject"] for row in rows})),
				day.day.isin(list({frappe.utils.getdate(row["day"]) for row in rows})),
			]
		)
	)


def _days_where(condition) -> dict:
	day = frappe.qb.DocType(DOCTYPE)
	found = (
		frappe.qb.from_(day)
		.select(day.name, day.service, day.subject, day.meter, day.dimension, day.day, day.aggregation)
		.select(day.quantity, day.as_of, day.estimated, day.invoice)
		.where(condition)
	).run(as_dict=True)
	return {_key(row): row for row in found}


def _insert(rows: list[dict], now) -> list[dict]:
	"""Insert these new days, and return the lines whose day another worker inserted first."""
	if not rows:
		return []
	user = frappe.session.user
	names = [frappe.generate_hash(length=12) for _row in rows]
	values = [
		(
			name,
			now,
			now,
			user,
			user,
			*(row.get(field) for field in _DAY_FIELDS),
			now,
			frappe.utils.cint(row.get("estimated")),
		)
		for name, row in zip(names, rows, strict=True)
	]
	frappe.db.bulk_insert(DOCTYPE, list(_INSERT_FIELDS), values, ignore_duplicates=True)
	# A day another worker inserted during this transaction is left alone: under snapshot isolation
	# any lock on that row is refused. This transaction sees its own inserts, so a missing name lost.
	stored = set(frappe.get_all(DOCTYPE, filters={"name": ["in", names]}, pluck="name"))
	return [row for name, row in zip(names, rows, strict=True) if name not in stored]


def _update(name: str, row: dict, now) -> None:
	"""Apply a newer line. The guard is in the WHERE, so a concurrent writer can never lower a day."""
	day = frappe.qb.DocType(DOCTYPE)
	if row["aggregation"] == LEVEL:
		newer_than_stored = day.quantity < row["quantity"]
	else:
		newer_than_stored = day.as_of < row["as_of"]
	(
		frappe.qb.update(day)
		.set(day.quantity, row["quantity"])
		.set(day.source_amount, row.get("source_amount"))
		.set(day.as_of, row.get("as_of"))
		.set(day.estimated, 0)
		.set(day.landed_at, now)
		.set(day.modified, now)
		.where((day.name == name) & day.invoice.isnull() & ((day.estimated == 1) | newer_than_stored))
	).run()
