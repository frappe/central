# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The subjects a pushed report's lines bill, day by day."""

import datetime

import frappe
from frappe.query_builder import Order

from central.billing.revenue.bundled_buckets import billed_subjects_of
from central.billing.revenue.usage_ledger import utc_day_start, utc_today
from central.services.doctype.service.service import STORAGE_SERVICE

# A service sends a deleted bucket's last days after the delete, so Central takes lines for a bucket
# deleted today or on the 2 UTC days before.
DELETED_SUBJECT_DAYS = 2


def subjects_by_day(service: str, names: list[str], days: set[str]) -> dict[str, dict]:
	"""The subjects among `names` that `service` bills on each of `days`, by day then subject."""
	billed = {day: billed_subjects_of(service, day, names) for day in days}
	# One lookup for every name missing on some day, so a day's answer never depends on the other
	# days sent with it: a name billed on one day may still be a deleted bucket on another.
	missing = {name for name in names for subjects in billed.values() if name not in subjects}
	deleted = _recently_deleted(service, sorted(missing))
	# A subject billed that day wins over a deleted bucket of the same name.
	return {day: {**_deleted_on(deleted, day), **subjects} for day, subjects in billed.items()}


def _deleted_on(deleted: dict, day: str) -> dict:
	"""The deleted buckets that still existed at some moment of the UTC day `day`."""
	start = utc_day_start(day)
	return {name: row for name, row in deleted.items() if row.deleted_at >= start}


def _recently_deleted(service: str, names: list[str]) -> dict:
	"""The latest recorded deletion of each of `names` in the last few UTC days, in one query."""
	# Only a team's own bucket is recorded when deleted; a server's backup bucket never is.
	if service != STORAGE_SERVICE or not names:
		return {}
	today = utc_today()
	since = utc_day_start(today - datetime.timedelta(days=DELETED_SUBJECT_DAYS))
	until = utc_day_start(today + datetime.timedelta(days=1))
	table = frappe.qb.DocType("Deleted Bucket")
	rows = (
		frappe.qb.from_(table)
		.select(table.external_id, table.team, table.subscription, table.deleted_at)
		.where(table.external_id.isin(names))
		.where(table.deleted_at >= since)
		.orderby(table.deleted_at, order=Order.desc)
		.orderby(table.creation, order=Order.desc)
	).run(as_dict=True)
	latest: dict = {}
	for row in rows:
		latest.setdefault(row.external_id, row)
	# A deletion stamped after today is a clock error, not a bucket that still bills.
	return {name: row for name, row in latest.items() if row.deleted_at < until}
