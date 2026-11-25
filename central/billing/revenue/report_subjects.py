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
	"""The deleted bucket of each name that was alive at some moment of the UTC day `day`."""
	start = utc_day_start(day)
	end = utc_day_start(frappe.utils.getdate(day) + datetime.timedelta(days=1))
	alive = {}
	for name, rows in deleted.items():
		# Created before the day ended and deleted after it began: that bucket held the name that day.
		# Rows run oldest first, so a day two buckets shared bills the one deleted first, as before.
		row = next((row for row in rows if row.created_at < end and row.deleted_at >= start), None)
		if row:
			alive[name] = row
	return alive


def _recently_deleted(service: str, names: list[str]) -> dict:
	"""Each of `names`' recorded deletions in the last few UTC days, oldest first, in one query."""
	# Only a team's own bucket is recorded when deleted; a server's backup bucket never is.
	if service != STORAGE_SERVICE or not names:
		return {}
	since = utc_day_start(utc_today() - datetime.timedelta(days=DELETED_SUBJECT_DAYS))
	table = frappe.qb.DocType("Deleted Bucket")
	rows = (
		frappe.qb.from_(table)
		.select(table.external_id, table.team, table.subscription, table.created_at, table.deleted_at)
		.where(table.external_id.isin(names))
		.where(table.deleted_at >= since)
		.orderby(table.deleted_at, order=Order.asc)
		.orderby(table.creation, order=Order.asc)
	).run(as_dict=True)
	deleted: dict = {}
	for row in rows:
		deleted.setdefault(row.external_id, []).append(row)
	return deleted
