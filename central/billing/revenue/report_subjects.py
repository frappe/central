# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The subjects a pushed report's lines bill, day by day."""

import datetime

import frappe
from frappe.query_builder import Order

from central.billing.revenue.bundled_buckets import bundled_buckets
from central.billing.revenue.usage_ledger import utc_today
from central.services.doctype.service.service import STORAGE_SERVICE
from central.services.doctype.team_service.team_service import billed_subjects

# A service sends a deleted subject's last day after the delete, so Central keeps taking it this long.
DELETED_SUBJECT_DAYS = 2


def subjects_by_day(service: str, names: list[str], days: set[str]) -> dict[str, dict]:
	"""The subjects among `names` that `service` bills on each of `days`, by day then subject."""
	known = billed_subjects(service, names)
	deleted = _recently_deleted(service, [name for name in names if name not in known])
	return {day: {**deleted, **_bundled_on(service, names, day), **known} for day in days}


def _bundled_on(service: str, names: list[str], day: str) -> dict:
	# A server's backup bucket bills only on a day its server billed, with that day's bundle.
	if service != STORAGE_SERVICE or not names:
		return {}
	return bundled_buckets(names, day)


def _recently_deleted(service: str, names: list[str]) -> dict:
	"""Subjects Central no longer has that billed a day in the last few days, by subject."""
	if not names:
		return {}
	day = frappe.qb.DocType("Usage Day")
	subscription = frappe.qb.DocType("Subscription")
	since = utc_today() - datetime.timedelta(days=DELETED_SUBJECT_DAYS)
	rows = (
		frappe.qb.from_(day)
		.join(subscription)
		.on(subscription.name == day.subscription)
		.select(day.subject.as_("external_id"), day.team, day.subscription)
		.where(day.service == service)
		.where(day.subject.isin(names))
		.where(day.day >= since)
		# A server's backup bucket bills only while its server bills, which is resolved by day.
		.where(subscription.server_id.isnull() | (subscription.server_id == ""))
		.orderby(day.day, order=Order.desc)
	).run(as_dict=True)
	latest: dict = {}
	for row in rows:
		latest.setdefault(row.external_id, row)
	return latest
