# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The subjects a pushed report's lines bill, day by day."""

import datetime

import frappe
from frappe.query_builder import Order
from frappe.query_builder.functions import Max

from central.billing.revenue.bundled_buckets import billed_subjects_of
from central.billing.revenue.usage_ledger import utc_today

# A service sends a deleted subject's last day after the delete, so Central takes a subject it no
# longer bills while its most recent Usage Day is within this many UTC days of today.
DELETED_SUBJECT_DAYS = 2


def subjects_by_day(service: str, names: list[str], days: set[str]) -> dict[str, dict]:
	"""The subjects among `names` that `service` bills on each of `days`, by day then subject."""
	billed = {day: billed_subjects_of(service, day, names) for day in days}
	known = {name for subjects in billed.values() for name in subjects}
	deleted = _recently_deleted(service, [name for name in names if name not in known])
	# A deleted subject's lines go on its last subscription for every reported day, a backlog too;
	# a subject billed that day wins over a deleted one of the same name.
	return {day: {**deleted, **subjects} for day, subjects in billed.items()}


def _recently_deleted(service: str, names: list[str]) -> dict:
	"""Subjects Central no longer bills whose own latest Usage Day is a recent team-level one."""
	today = utc_today()
	since = today - datetime.timedelta(days=DELETED_SUBJECT_DAYS)
	# Only the subject's single latest day counts: an older recent row must not stand in for a
	# latest day on a server's subscription (resolved by day) or one dated after today.
	return {
		row.external_id: frappe._dict(
			external_id=row.external_id, team=row.team, subscription=row.subscription
		)
		for row in _latest_usage_days(service, names)
		if since <= row.day <= today and not row.server_id
	}


def _latest_usage_days(service: str, names: list[str]) -> list:
	"""Each subject's latest Usage Day for `service`, over all its subscriptions, in two queries."""
	if not names:
		return []
	day = frappe.qb.DocType("Usage Day")
	latest = dict(
		frappe.qb.from_(day)
		.select(day.subject, Max(day.day))
		.where(day.service == service)
		.where(day.subject.isin(names))
		.groupby(day.subject)
		.run()
	)
	if not latest:
		return []
	subscription = frappe.qb.DocType("Subscription")
	rows = (
		frappe.qb.from_(day)
		.join(subscription)
		.on(subscription.name == day.subscription)
		.select(day.subject.as_("external_id"), day.team, day.subscription, day.day, subscription.server_id)
		.where(day.service == service)
		.where(day.subject.isin(list(latest)))
		.where(day.day.isin(list(set(latest.values()))))
		.orderby(day.creation, order=Order.desc)
	).run(as_dict=True)
	# Another subject's latest day can match this subject's older day, so keep exact matches.
	first: dict = {}
	for row in rows:
		if row.day == latest[row.external_id]:
			first.setdefault(row.external_id, row)
	return list(first.values())
