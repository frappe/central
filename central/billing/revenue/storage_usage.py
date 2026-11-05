# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import calendar
import datetime
from collections import defaultdict

import frappe

from central.billing.doctype.billing_profile.billing_profile import get_team_currency
from central.billing.revenue.metering import ingest_rollup, live_rollup

# Cargo counts and caps buckets in GiB; billing names the unit GB.
BYTES_PER_GIB = 1024**3
RESOURCE_TYPE = "Storage"


def record_storage_usage(today: datetime.date | str | None = None) -> dict:
	"""Daily: bill every storage subscription by the GB-day for the days since its last reading."""
	today = frappe.utils.getdate(today)
	recorded, failed = 0, 0
	for subscription, buckets in _buckets_by_subscription().items():
		try:
			frappe.db.savepoint("storage_usage")
			record_subscription_usage(subscription, buckets, today)
			recorded += 1
		except Exception:
			# One unreachable region must not stop the others; the next reading bills the missed days.
			frappe.db.rollback(save_point="storage_usage")
			frappe.log_error(title=f"Storage usage for {subscription} was not recorded")
			failed += 1
	return {"recorded": recorded, "failed": failed}


def record_subscription_usage(subscription: str, buckets: list, today: datetime.date) -> str | None:
	"""Bill each day since the last reading at today's GB, so a missed day loses no usage."""
	sub = frappe.db.get_value(
		"Subscription", subscription, ["team", "cluster", "service_subject", "start_date"], as_dict=True
	)
	month_start = today.replace(day=1)
	key = f"storage::{sub.service_subject}::{month_start:%Y-%m}"
	new_days = today.day - _days_billed(key, sub.start_date, month_start)
	if new_days <= 0:
		return key

	gib = sum(frappe.utils.flt(bucket.get_usage().get("used_bytes")) for bucket in buckets) / BYTES_PER_GIB
	days_in_month = calendar.monthrange(today.year, today.month)[1]
	return ingest_rollup(
		{
			"idempotency_key": key,
			"resource_id": sub.service_subject,
			"resource_type": RESOURCE_TYPE,
			"meter_type": "Gauge",
			"team": sub.team,
			"cluster": sub.cluster,
			"currency": get_team_currency(sub.team),
			"period_start": month_start,
			"period_end": today.replace(day=days_in_month),
			"quantity": gib * new_days / days_in_month,
			"unit": "GB",
			"sequence": today.day,
		}
	)


def _days_billed(key: str, start_date, month_start: datetime.date) -> int:
	"""The last day of the month already billed: the latest reading, or the day before the subscription began."""
	rollup = frappe.db.get_value("Usage Rollup", {"idempotency_key": key}, "name")
	if rollup:
		return frappe.utils.cint(frappe.db.get_value("Usage Rollup", live_rollup(rollup), "sequence"))
	started = frappe.utils.getdate(start_date) if start_date else month_start
	return started.day - 1 if started >= month_start else 0


def _buckets_by_subscription() -> dict[str, list]:
	"""Every live bucket, grouped by the storage subscription that bills it."""
	from central.services.doctype.team_service.team_service import STORAGE_SERVICE

	grouped = defaultdict(list)
	for name in frappe.get_all(
		"Team Service",
		filters={"add_on_service": STORAGE_SERVICE, "status": "Active", "subscription": ["is", "set"]},
		pluck="name",
	):
		bucket = frappe.get_doc("Team Service", name)
		grouped[bucket.subscription].append(bucket)
	return grouped
