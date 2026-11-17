# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe

from central.billing.platform.jobs import each_isolated
from central.billing.revenue.usage_ledger import utc_today, write_days
from central.services.doctype.service.service import STORAGE_SERVICE

METER = "bytes_stored"
PAGE_SIZE = 100


def read_storage_usage() -> int:
	"""Hourly, until Cargo reports usage itself: read every bucket and keep each day's peak."""
	from central.billing.revenue.invoicing.run import billing_queue

	if not frappe.db.get_value("Service", STORAGE_SERVICE, "central_reads"):
		return 0
	names = billed_buckets()
	for start in range(0, len(names), PAGE_SIZE):
		frappe.enqueue(
			"central.billing.revenue.storage_bridge.read_page",
			queue=billing_queue(),
			names=names[start : start + PAGE_SIZE],
		)
	return len(names)


def read_page(names: list[str]) -> int:
	"""Read one page of buckets. A bucket Cargo cannot answer for is logged and skipped."""
	meter = frappe.get_doc("Service", STORAGE_SERVICE).get_meter(METER)
	rows = each_isolated("Storage usage", "Team Service", names, lambda name: _reading(name, meter))
	return write_days(rows)


def billed_buckets() -> list[str]:
	"""Every bucket that bills a subscription, suspended ones included: they still hold data."""
	return frappe.get_all(
		"Team Service",
		filters={"add_on_service": STORAGE_SERVICE, "subscription": ["is", "set"]},
		pluck="name",
		order_by="name asc",
	)


def _reading(name: str, meter) -> dict:
	bucket = frappe.get_doc("Team Service", name)
	used = frappe.utils.flt(bucket.get_usage().get("used_bytes"))
	return {
		"service": STORAGE_SERVICE,
		"meter": meter.meter_key,
		"subject": bucket.external_id or bucket.bucket_name,
		"day": utc_today(),
		"aggregation": meter.aggregation,
		"team": bucket.team,
		"subscription": bucket.subscription,
		"resource_type": meter.resource_type,
		"quantity": used / frappe.utils.flt(meter.unit_divisor),
		"unit": meter.unit,
		"as_of": frappe.utils.now_datetime(),
	}
