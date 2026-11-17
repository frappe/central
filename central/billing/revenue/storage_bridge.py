# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe

from central.billing.revenue.usage_ledger import utc_today, write_days
from central.services.doctype.service.service import STORAGE_METER, STORAGE_SERVICE
from central.services.doctype.team_service.team_service import billed_subjects


def read_storage_usage() -> int:
	"""Hourly, until Cargo reports usage itself: read every bucket and keep each day's peak."""
	from central.billing.revenue.invoicing.run import billing_queue

	if not frappe.db.get_value("Service", STORAGE_SERVICE, "central_reads"):
		return 0
	regions = billed_buckets()
	for region, names in regions.items():
		frappe.enqueue(
			"central.billing.revenue.storage_bridge.read_region",
			queue=billing_queue(),
			region=region,
			names=names,
		)
	return sum(len(names) for names in regions.values())


def read_region(region: str, names: list[str]) -> int:
	"""Read one region's buckets. The buckets Cargo cannot answer for are logged once, as a count."""
	meter = frappe.get_doc("Service", STORAGE_SERVICE).get_meter(STORAGE_METER)
	rows, failed = [], []
	for name in names:
		# One bucket's failure, of any kind, must not stop the region's other buckets.
		try:
			rows.append(_reading(name, meter))
		except Exception as error:
			failed.append(f"{name}: {error!r}")
	if failed:
		frappe.log_error(
			title=f"Storage usage: {len(failed)} bucket(s) not read in {region}",
			message="\n".join(failed[:50]),
			reference_doctype="Region",
			reference_name=region,
		)
	return write_days(rows)


def billed_buckets() -> dict[str, list[str]]:
	"""Every bucket that bills a subscription, by region. Suspended ones still hold data."""
	regions: dict[str, list[str]] = {}
	for bucket in billed_subjects(STORAGE_SERVICE).values():
		regions.setdefault(bucket.region, []).append(bucket.name)
	return regions


def _reading(name: str, meter) -> dict:
	bucket = frappe.get_doc("Team Service", name)
	used = frappe.utils.flt(bucket.get_usage().get("used_bytes"))
	return meter.get_day_row(bucket, utc_today(), used, as_of=frappe.utils.now_datetime())
