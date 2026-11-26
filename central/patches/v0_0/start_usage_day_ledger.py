import calendar

import frappe

from central.services.doctype.service.service import (
	AI_SERVICE,
	STORAGE_METER,
	STORAGE_SERVICE,
	ensure_services,
)

GIB = 1024**3
WRITE_PAGE = 500


def execute():
	"""Start the Usage Day ledger without losing the storage this month already read."""
	if not frappe.db.table_exists("Usage Day"):
		return
	ensure_services()
	_name_subjects()
	_mark_invoiced_months()
	_carry_this_month()


def _name_subjects() -> None:
	"""Name each subject the way its service reports it."""
	service = frappe.qb.DocType("Team Service")
	(
		frappe.qb.update(service)
		.set(service.external_id, service.bucket_name)
		.where((service.add_on_service == STORAGE_SERVICE) & service.external_id.isnull())
	).run()
	(
		frappe.qb.update(service)
		.set(service.external_id, service.team)
		.where((service.add_on_service == AI_SERVICE) & service.external_id.isnull())
	).run()


def _mark_invoiced_months() -> None:
	"""A rollup whose month already has a live invoice was billed by it."""
	month_start = frappe.utils.getdate().replace(day=1)
	rollups = frappe.get_all(
		"Usage Rollup",
		filters={"invoice": ["is", "not set"], "period_start": ["<", month_start]},
		fields=["name", "team", "period_start"],
	)
	invoices = {
		(invoice.team, frappe.utils.getdate(invoice.period_start)): invoice.name
		for invoice in frappe.get_all(
			"Invoice",
			filters={"team": ["in", list({r.team for r in rollups})], "status": ["!=", "Cancelled"]},
			fields=["name", "team", "period_start"],
		)
	}
	billed: dict[str, list[str]] = {}
	for rollup in rollups:
		invoice = invoices.get((rollup.team, frappe.utils.getdate(rollup.period_start).replace(day=1)))
		if invoice:
			billed.setdefault(invoice, []).append(rollup.name)

	table = frappe.qb.DocType("Usage Rollup")
	for invoice, names in billed.items():
		frappe.qb.update(table).set(table.invoice, invoice).where(table.name.isin(names)).run()


def _carry_this_month() -> None:
	"""Carry this month's storage figure into estimated days before today, in GB."""
	# Imported here, so the patch still loads when the billing modules it uses change.
	from central.billing.revenue.usage_ledger import utc_today, write_central_days
	from central.billing.revenue.usage_reports import ESTIMATED

	# The old job kept one GiB-month figure over the days it read; today on, the hourly read counts.
	today = utc_today()
	month_start = today.replace(day=1)
	days_in_month = calendar.monthrange(month_start.year, month_start.month)[1]
	rollups = frappe.get_all(
		"Usage Rollup",
		filters={
			"resource_type": "Storage",
			"period_start": month_start,
			"invoice": ["is", "not set"],
			"superseded_by": ["is", "not set"],
		},
		fields=["resource_id", "team", "quantity", "sequence"],
	)
	subscriptions = dict(
		frappe.get_all(
			"Subscription",
			filters={"service_subject": ["in", [r.resource_id for r in rollups]]},
			fields=["service_subject", "name"],
			as_list=True,
		)
	)
	meter = frappe.get_doc("Service", STORAGE_SERVICE).get_meter(STORAGE_METER)
	rows = [
		row
		for rollup in rollups
		for row in _carried_days(meter, rollup, subscriptions.get(rollup.resource_id), today, days_in_month)
	]
	for start in range(0, len(rows), WRITE_PAGE):
		write_central_days(rows[start : start + WRITE_PAGE], ESTIMATED)


def _carried_days(meter, rollup, subscription: str | None, today, days_in_month: int) -> list[dict]:
	days_read = frappe.utils.cint(rollup.sequence)
	if not days_read or not subscription:
		return []
	subject = frappe._dict(
		external_id=f"{rollup.resource_id}::before-ledger", team=rollup.team, subscription=subscription
	)
	bytes_a_day = frappe.utils.flt(rollup.quantity) * days_in_month / days_read * GIB
	return [
		meter.get_day_row(subject, today.replace(day=day), bytes_a_day, estimated=1)
		for day in range(1, min(days_read, today.day - 1) + 1)
	]
