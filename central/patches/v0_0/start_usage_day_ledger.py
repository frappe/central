import calendar

import frappe

from central.billing.revenue.usage_ledger import write_days
from central.services.doctype.service.service import BYTES_PER_GB, STORAGE_SERVICE, ensure_services

GIB = 1024**3


def execute():
	"""Start the Usage Day ledger (ADR 0026): register storage, name each subject the way its
	service reports it, mark months already invoiced as billed, and carry this month's storage
	figure into estimated days so the first recount does not drop the days read before it."""
	ensure_services()
	_name_subjects()
	_mark_invoiced_months()
	_carry_this_month()


def _name_subjects() -> None:
	service = frappe.qb.DocType("Team Service")
	(
		frappe.qb.update(service)
		.set(service.external_id, service.bucket_name)
		.where((service.add_on_service == STORAGE_SERVICE) & service.external_id.isnull())
	).run()
	(
		frappe.qb.update(service)
		.set(service.external_id, service.team)
		.where((service.add_on_service == "ai") & service.external_id.isnull())
	).run()


def _mark_invoiced_months() -> None:
	"""A rollup whose month already has a live invoice was billed by it."""
	month_start = frappe.utils.getdate().replace(day=1)
	for rollup in frappe.get_all(
		"Usage Rollup",
		filters={"invoice": ["is", "not set"], "period_start": ["<", month_start]},
		fields=["name", "team", "period_start"],
	):
		invoice = frappe.db.get_value(
			"Invoice",
			{
				"team": rollup.team,
				"period_start": frappe.utils.getdate(rollup.period_start).replace(day=1),
				"status": ["!=", "Cancelled"],
			},
			"name",
		)
		if invoice:
			frappe.db.set_value("Usage Rollup", rollup.name, "invoice", invoice, update_modified=False)


def _carry_this_month() -> None:
	"""The old job kept one running GiB-month figure and the last day it read. Spread that
	average over the days read, in GB, as estimated days on a subject of their own."""
	month_start = frappe.utils.getdate().replace(day=1)
	days_in_month = calendar.monthrange(month_start.year, month_start.month)[1]
	for rollup in frappe.get_all(
		"Usage Rollup",
		filters={
			"resource_type": "Storage",
			"period_start": month_start,
			"invoice": ["is", "not set"],
			"superseded_by": ["is", "not set"],
		},
		fields=["resource_id", "team", "quantity", "sequence"],
	):
		_carry(rollup, month_start, days_in_month)


def _carry(rollup, month_start, days_in_month: int) -> None:
	days_read = frappe.utils.cint(rollup.sequence)
	subscription = frappe.db.get_value("Subscription", {"service_subject": rollup.resource_id}, "name")
	if not days_read or not subscription:
		return
	gb = frappe.utils.flt(rollup.quantity) * days_in_month / days_read * GIB / BYTES_PER_GB
	write_days(
		[
			{
				"service": STORAGE_SERVICE,
				"meter": "bytes_stored",
				"subject": f"{rollup.resource_id}::before-ledger",
				"day": month_start.replace(day=day),
				"aggregation": "Level",
				"team": rollup.team,
				"subscription": subscription,
				"resource_type": "Storage",
				"quantity": gb,
				"unit": "GB",
				"estimated": 1,
			}
			for day in range(1, days_read + 1)
		]
	)
