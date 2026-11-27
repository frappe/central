# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from central.billing.revenue import usage_month, usage_reports
from central.billing.revenue.rollup_updates import is_allowance_corrected, is_version_mark
from central.services.doctype.service.service import is_read_by_central

WATERMARK = "usage_month_fold_watermark"
DAY_DOCTYPE = "Usage Day"
PAGE_SIZE = 1000
# A day written by a worker that started before the fold may commit a little after it.
OVERLAP_MINUTES = 5
_DAY_FIELDS = (
	"name",
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
	"estimated",
	"written_off",
	"invoice",
)
_ROLLUP_FIELDS = (
	"name",
	"idempotency_key",
	"resource_id",
	"resource_type",
	"dimension",
	"team",
	"cluster",
	"period_start",
	"quantity",
	"unit",
	"currency",
	"locked_allowance",
	"locked_rate",
	"rate_date",
	"invoice",
	"superseded_by",
	"modified",
)


def fold_all() -> None:
	"""Fold every Usage Day and every rollup the recount wrote into month rows, and check the totals."""
	# Taken before the read, so a day written while the fold runs is folded again by the next recount.
	started = frappe.utils.now_datetime()
	days = frappe.get_all(DAY_DOCTYPE, fields=list(_DAY_FIELDS), order_by="name asc")
	folded = fold(days, ledger_rollups())
	_check_totals(days, folded)
	frappe.db.set_default(WATERMARK, str(started))


def fold_stragglers() -> None:
	"""Fold days and rollups an older worker wrote after the fold, so none is lost."""
	since = frappe.db.get_default(WATERMARK)
	if not since:
		return
	now = frappe.utils.now_datetime()
	since = frappe.utils.add_to_date(since, minutes=-OVERLAP_MINUTES)
	days = _days_changed_since(since)
	rollups = ledger_rollups(modified_after=since)
	if days or rollups:
		fold(days, rollups)
	frappe.db.set_default(WATERMARK, str(now))


def fold(days: list, rollups: list) -> list:
	"""Write days and rollups into month rows, and return the rollups folded. Running it again changes nothing."""
	reports = _migrated_reports(days, rollups)
	for start in range(0, len(days), PAGE_SIZE):
		_fold_days(days[start : start + PAGE_SIZE], reports)
	folded = _fold_rollups(rollups)
	keys = {_base_key(rollup.idempotency_key) for rollup in folded}
	# A folded rollup goes with every earlier version of it.
	versions = [rollup.name for rollup in rollups if _base_key(rollup.idempotency_key) in keys]
	if versions:
		frappe.db.delete("Usage Rollup", {"name": ["in", versions]})
	return folded


def _base_key(idempotency_key: str) -> str:
	"""A rollup's key without the version marks an operator's corrections added."""
	parts = idempotency_key.split("::")
	while len(parts) > 3 and is_version_mark(parts[-1], "va"):
		parts.pop()
	return "::".join(parts)


def ledger_rollups(modified_after=None) -> list:
	"""The rollups the usage recount wrote, which month rows replace. A reported total stays."""
	services = frappe.get_all("Service", pluck="name")
	table = frappe.qb.DocType("Usage Rollup")
	query = frappe.qb.from_(table).select(*(table[name] for name in _ROLLUP_FIELDS))
	is_ledger = None
	for service in services:
		condition = table.idempotency_key.like(f"{service}::%")
		is_ledger = condition if is_ledger is None else is_ledger | condition
	if is_ledger is None:
		return []
	query = query.where(is_ledger)
	if modified_after:
		query = query.where(table.modified > modified_after)
	return query.orderby(table.name).run(as_dict=True)


def _days_changed_since(since) -> list:
	"""Days written, or billed by an invoice made, after `since`."""
	day = frappe.qb.DocType(DAY_DOCTYPE)
	invoice = frappe.qb.DocType("Invoice")
	recent_invoices = frappe.qb.from_(invoice).select(invoice.name).where(invoice.creation > since)
	return (
		frappe.qb.from_(day)
		.select(*(day[name] for name in _DAY_FIELDS))
		.where((day.modified > since) | day.invoice.isin(recent_invoices))
		.orderby(day.name)
	).run(as_dict=True)


def _migrated_reports(days: list, rollups: list) -> dict[str, str]:
	"""One report per service that keeps the days and rollups folded, as the evidence they carry."""
	by_service: dict[str, dict] = {}
	for day in days:
		by_service.setdefault(day.service, {"usage_days": [], "rollups": []})["usage_days"].append(day)
	for rollup in rollups:
		service = rollup.idempotency_key.split("::", 1)[0]
		by_service.setdefault(service, {"usage_days": [], "rollups": []})["rollups"].append(rollup)
	return {
		service: usage_reports.record(
			service,
			usage_reports.MIGRATED,
			usage_reports.canonical_json(kept),
			line_count=len(kept["usage_days"]) + len(kept["rollups"]),
		)
		for service, kept in by_service.items()
	}


def _fold_days(days: list, reports: dict[str, str]) -> None:
	for service in {day.service for day in days}:
		_write_service_days(service, [day for day in days if day.service == service], reports[service])
	_stamp_folded([day for day in days if day.invoice])


def _write_service_days(service: str, days: list, report: str) -> None:
	source = usage_reports.READ_BY_CENTRAL if is_read_by_central(service) else usage_reports.PUSHED
	if usage_month.write_lines([_line(day) for day in days], report, source).conflicts:
		# Nothing is lost: the fold runs again with the same days.
		raise frappe.QueryDeadlockError(_("Usage days changed while they were folded."))


def _stamp_folded(billed: list) -> None:
	"""Mark each folded day billed by the invoice that billed its Usage Day."""
	holding = _holding_rows(billed)
	by_invoice: dict[str, dict] = {}
	for day in billed:
		number = frappe.utils.getdate(day.day).day
		masks = by_invoice.setdefault(day.invoice, {})
		name = holding[(*_day_key(day), number)]
		masks[name] = masks.get(name, 0) | usage_month.bit(number)
	for invoice, masks in by_invoice.items():
		usage_month.stamp_days(masks, invoice)


def _line(day) -> dict:
	line = {name: day[name] for name in _DAY_FIELDS if name not in ("name", "invoice")}
	line["dimension"] = day.dimension or ""
	if not frappe.utils.flt(day.included):
		# A day without a bundle stores none.
		line.pop("included")
	return line


def _day_key(row) -> tuple:
	return (
		row.service,
		row.subject,
		row.meter,
		row.dimension or "",
		usage_month.month_of(row.get("day") or row.month),
	)


def _holding_rows(days: list) -> dict[tuple, str]:
	"""The month row that holds each of these days, by day key and day of the month."""
	if not days:
		return {}
	rows = frappe.get_all(
		usage_month.DOCTYPE,
		filters={
			"subject": ["in", list({day.subject for day in days})],
			"month": ["in", list({usage_month.month_of(day.day) for day in days})],
		},
		fields=["name", "service", "subject", "meter", "dimension", "month", "filled"],
	)
	return {(*_day_key(row), number): row.name for row in rows for number in usage_month.days_of(row.filled)}


def _fold_rollups(rollups: list) -> list:
	"""Copy each rollup's quantity, terms and invoice onto the month row that carries its month."""
	heads = [rollup for rollup in rollups if not rollup.superseded_by]
	meters = _meters_of(heads)
	folded = []
	for rollup in heads:
		meter = meters.get((rollup.resource_id, rollup.resource_type, rollup.dimension or ""))
		if not meter:
			# Kept as a rollup, which still bills: no day of it is left to fold it into.
			frappe.logger("billing").warning(f"Usage rollup {rollup.name} has no usage days to fold into")
			continue
		_fold_rollup(rollup, _carrier_of(rollup, meter))
		folded.append(rollup)
	return folded


def _fold_rollup(rollup, carrier) -> None:
	if carrier.invoice:
		return
	billed = max(0.0, frappe.utils.flt(rollup.quantity) - frappe.utils.flt(rollup.locked_allowance))
	frappe.db.set_value(
		usage_month.DOCTYPE,
		carrier.name,
		{
			"resource_id": rollup.resource_id,
			"cluster": rollup.cluster,
			"quantity": rollup.quantity,
			"currency": rollup.currency,
			"locked_allowance": rollup.locked_allowance,
			"locked_rate": rollup.locked_rate,
			"rate_date": rollup.rate_date,
			"terms_corrected": int(is_allowance_corrected(rollup.idempotency_key)),
			"invoice": rollup.invoice,
			"billed_quantity": billed if rollup.invoice else 0,
			"counted_at": rollup.modified,
		},
		update_modified=False,
	)


def _carrier_of(rollup, meter) -> frappe._dict:
	"""The month row that carries the rollup's month, on the subscription that holds that month's days."""
	month = usage_month.month_of(rollup.period_start)
	held = sorted((row for row in meter.rows if row.month == month), key=lambda row: row.name)
	subscription = held[0].subscription if held else meter.subscription
	return usage_month.carrier_of(frappe._dict(meter, subscription=subscription), month)


def _meters_of(rollups: list) -> dict[tuple, frappe._dict]:
	"""The meter whose days each rollup counted, with its month rows, by resource, type and dimension."""
	resources = list({rollup.resource_id for rollup in rollups}) or [""]
	subscription = frappe.qb.DocType("Subscription")
	owners = (
		frappe.qb.from_(subscription)
		.select(subscription.name, subscription.service_subject, subscription.server_id)
		.where(subscription.service_subject.isin(resources) | subscription.server_id.isin(resources))
	).run(as_dict=True)
	resource_of = {owner.name: owner.service_subject or owner.server_id for owner in owners}
	months = frappe.get_all(
		usage_month.DOCTYPE,
		filters={"subscription": ["in", list(resource_of) or [""]]},
		fields=[
			"name",
			"service",
			"meter",
			"subject",
			"subscription",
			"aggregation",
			"team",
			"unit",
			"resource_type",
			"dimension",
			"month",
			"counted_at",
			"invoice",
		],
		order_by="month asc",
	)
	meters: dict[tuple, frappe._dict] = {}
	for month in months:
		key = (resource_of[month.subscription], month.resource_type, month.dimension)
		meter = meters.setdefault(key, frappe._dict(month, day_subject=month.subject, rows=[]))
		# The latest month names the meter a month with no days of its own is made for.
		meter.update(
			{name: month[name] for name in ("subject", "subscription", "team")}, day_subject=month.subject
		)
		meter.rows.append(month)
	return meters


def _check_totals(days: list, rollups: list) -> None:
	"""Each team's months hold the quantity its rollups held and the days it had."""
	expected_quantity: dict = {}
	for rollup in rollups:
		if not rollup.superseded_by:
			key = (rollup.team, usage_month.month_of(rollup.period_start))
			expected_quantity[key] = expected_quantity.get(key, 0.0) + frappe.utils.flt(rollup.quantity)
	expected_days: dict = {}
	for day in days:
		key = (day.team, usage_month.month_of(day.day))
		expected_days[key] = expected_days.get(key, 0) + 1
	quantity, filled = _month_totals()
	for key, value in expected_quantity.items():
		if abs(quantity.get(key, 0.0) - value) > 1e-6:
			frappe.throw(
				_("Usage of {0} in {1} is {2}, not {3}.").format(key[0], key[1], quantity.get(key), value)
			)
	for key, count in expected_days.items():
		if filled.get(key, 0) != count:
			frappe.throw(
				_("{0} has {1} days in {2}, not {3}.").format(key[0], filled.get(key, 0), key[1], count)
			)


def _month_totals() -> tuple[dict, dict]:
	"""Each team's counted quantity and number of days, by month."""
	quantity: dict = {}
	filled: dict = {}
	for month in frappe.get_all(
		usage_month.DOCTYPE, fields=["team", "month", "quantity", "counted_at", "filled"]
	):
		key = (month.team, month.month)
		if month.counted_at:
			quantity[key] = quantity.get(key, 0.0) + frappe.utils.flt(month.quantity)
		filled[key] = filled.get(key, 0) + bin(month.filled).count("1")
	return quantity, filled
