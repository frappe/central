# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import calendar
import datetime

import frappe

from central.billing.doctype.billing_profile.billing_profile import get_team_currency
from central.billing.platform.jobs import each_isolated
from central.billing.revenue.metering import ingest_rollup, live_rollup
from central.billing.revenue.usage_ledger import DOCTYPE, LEVEL

WATERMARK = "usage_recount_watermark"
PAGE_SIZE = 200
# A month is looked at this many months ahead for an unbilled one before giving up.
MONTHS_AHEAD = 24
_SEPARATOR = "|"


def recount_changed(now=None) -> int:
	"""Hourly: recompute the monthly figure of every subscription whose days changed since the last run."""
	from central.billing.revenue.invoicing.run import billing_queue

	now = frappe.utils.get_datetime(now) if now else frappe.utils.now_datetime()
	since = frappe.db.get_default(WATERMARK) or "2000-01-01 00:00:00"
	months = sorted(_changed_months(since, now))
	for start in range(0, len(months), PAGE_SIZE):
		frappe.enqueue(
			"central.billing.revenue.usage_recount.recount_page",
			queue=billing_queue(),
			months=months[start : start + PAGE_SIZE],
		)
	frappe.db.set_default(WATERMARK, str(now))
	return len(months)


def recount_page(months: list[str]) -> None:
	each_isolated("Usage recount", "Subscription", months, _recount_encoded)


def recount_team(team: str, period_end) -> None:
	"""Recompute every usage month of the team that has unbilled days up to `period_end`."""
	month = frappe.utils.getdate(period_end).replace(day=1)
	for subscription, resource_type in _unbilled_meters(team, period_end):
		recount_month(subscription, resource_type, month)


def recount_month(subscription: str, resource_type: str, month) -> str | None:
	"""Write the first unbilled month at or after `month` from the days not yet billed.

	A billed month is never recounted, so a day that arrives after its month was billed goes
	into the next unbilled month. A Level day counts as its peak over the days in its own month
	(GB-month, as Cloudflare R2 bills storage); a Sum day counts as its total.
	"""
	sample = frappe.db.get_value(
		DOCTYPE,
		{"subscription": subscription, "resource_type": resource_type},
		["service", "unit", "aggregation"],
		as_dict=True,
	)
	if not sample:
		return None
	sub = frappe.db.get_value(
		"Subscription", subscription, ["team", "cluster", "service_subject"], as_dict=True
	)
	target = _unbilled_month(sample.service, sub.service_subject, frappe.utils.getdate(month).replace(day=1))
	days = frappe.get_all(
		DOCTYPE,
		filters={
			"subscription": subscription,
			"resource_type": resource_type,
			"invoice": ["is", "not set"],
			"day": ["<=", _month_end(target)],
		},
		fields=["day", "quantity", "aggregation"],
	)
	billed = _billed_months(sub.service_subject, resource_type)
	# An earlier day counts here only once its own month was billed; until then it is that month's.
	days = [day for day in days if _month_of(day.day) == target or _month_of(day.day) in billed]
	return ingest_rollup(
		{
			"idempotency_key": rollup_key(sample.service, sub.service_subject, target),
			"resource_id": sub.service_subject,
			"resource_type": resource_type,
			"meter_type": "Gauge" if sample.aggregation == LEVEL else "Counter",
			"team": sub.team,
			"cluster": sub.cluster,
			"currency": get_team_currency(sub.team),
			"period_start": target,
			"period_end": _month_end(target),
			"quantity": sum(_weight(day) for day in days),
			"unit": sample.unit,
		}
	)


def rollup_key(service: str, resource_id: str, month: datetime.date) -> str:
	return f"{service}::{resource_id}::{month:%Y-%m}"


def _recount_encoded(encoded: str) -> str | None:
	subscription, resource_type, month = encoded.split(_SEPARATOR)
	return recount_month(subscription, resource_type, month)


def _changed_months(since, now) -> set[str]:
	day = frappe.qb.DocType(DOCTYPE)
	rows = (
		frappe.qb.from_(day)
		.select(day.subscription, day.resource_type, day.day)
		.distinct()
		.where((day.landed_at > since) & (day.landed_at <= now) & day.resource_type.isnotnull())
	).run()
	return {
		_SEPARATOR.join((subscription, resource_type, f"{frappe.utils.getdate(on):%Y-%m-01}"))
		for subscription, resource_type, on in rows
	}


def _unbilled_meters(team: str, period_end) -> set[tuple]:
	day = frappe.qb.DocType(DOCTYPE)
	return set(
		(
			frappe.qb.from_(day)
			.select(day.subscription, day.resource_type)
			.distinct()
			.where(
				(day.team == team)
				& day.invoice.isnull()
				& (day.day <= period_end)
				& day.resource_type.isnotnull()
			)
		).run()
	)


def _unbilled_month(service: str, resource_id: str, month: datetime.date) -> datetime.date:
	"""`month`, or the first month after it whose rollup no invoice has billed yet."""
	for _ in range(MONTHS_AHEAD):
		name = frappe.db.get_value(
			"Usage Rollup", {"idempotency_key": rollup_key(service, resource_id, month)}, "name"
		)
		if not name or not frappe.db.get_value("Usage Rollup", live_rollup(name), "invoice"):
			return month
		month = frappe.utils.getdate(frappe.utils.add_months(month, 1))
	return month


def _billed_months(resource_id: str, resource_type: str) -> set[datetime.date]:
	"""The months of this subject's rollups that an invoice has billed."""
	return {
		_month_of(start)
		for start in frappe.get_all(
			"Usage Rollup",
			filters={"resource_id": resource_id, "resource_type": resource_type, "invoice": ["is", "set"]},
			pluck="period_start",
		)
	}


def _month_of(on) -> datetime.date:
	return frappe.utils.getdate(on).replace(day=1)


def _weight(day) -> float:
	quantity = frappe.utils.flt(day.quantity)
	if day.aggregation != LEVEL:
		return quantity
	on = frappe.utils.getdate(day.day)
	return quantity / calendar.monthrange(on.year, on.month)[1]


def _month_end(month: datetime.date) -> datetime.date:
	return month.replace(day=calendar.monthrange(month.year, month.month)[1])
