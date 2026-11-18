# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import calendar
import datetime
from dataclasses import dataclass, field

import frappe

from central.billing.doctype.billing_profile.billing_profile import get_team_currency
from central.billing.doctype.billing_run_team.billing_run_team import FAILED
from central.billing.platform.jobs import each_isolated
from central.billing.revenue import usage_ledger
from central.billing.revenue.metering import ingest_rollup, live_rollup
from central.billing.revenue.usage_ledger import DOCTYPE, LEVEL

WATERMARK = "usage_recount_watermark"
PAGE_SIZE = 200
# Past this many months with a billed rollup, the recount stops and logs a warning.
MONTHS_AHEAD = 24
_SEPARATOR = "|"


@dataclass
class MonthCount:
	"""One usage month as a recount wrote it."""

	month: datetime.date
	rollup: str
	days: list[str]


@dataclass
class Counted:
	"""The rollups and days a draft billed."""

	rollups: list[str] = field(default_factory=list)
	days: list[str] = field(default_factory=list)


def recount_changed(now=None) -> int:
	"""Hourly: recompute the monthly figure of every subscription whose days changed since the last run."""
	from central.billing.revenue.invoicing.run import billing_queue

	now = frappe.utils.get_datetime(now) if now else frappe.utils.now_datetime()
	# Overlap the last run, so a day whose transaction committed after that scan is still seen.
	since = frappe.utils.add_to_date(frappe.db.get_default(WATERMARK) or "2000-01-01", minutes=-5)
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


def recount_team(team: str, period_end) -> Counted:
	"""Recompute the team's usage for the month that ends on `period_end`, and return what was counted."""
	month = _month_of(period_end)
	counted = Counted()
	for subscription, resource_type in _unbilled_meters(team, period_end):
		written = recount_month(subscription, resource_type, month, drafting=True)
		if written and written.month == month:
			counted.rollups.append(written.rollup)
			counted.days.extend(written.days)
	return counted


def stamp_invoice(counted: Counted, invoice: str) -> None:
	"""Mark the rollups and days the invoice billed."""
	rollup = frappe.qb.DocType("Usage Rollup")
	if counted.rollups:
		(
			frappe.qb.update(rollup)
			.set(rollup.invoice, invoice)
			.where(rollup.name.isin(counted.rollups) & rollup.invoice.isnull())
		).run()
	usage_ledger.stamp_days(counted.days, invoice)


def release_invoice(invoice: str) -> None:
	"""Unmark what a cancelled invoice billed, so the invoice that replaces it bills it again."""
	rollup = frappe.qb.DocType("Usage Rollup")
	frappe.qb.update(rollup).set(rollup.invoice, None).where(rollup.invoice == invoice).run()
	usage_ledger.release_days(invoice)


def recount_month(subscription: str, resource_type: str, month, drafting: bool = False) -> MonthCount | None:
	"""Write the first open month at or after `month` from the days not yet billed."""
	# A billed or closed month is never recounted, so its late days go into the next open month.
	# The month a draft is billing stays open, even when an earlier draft of it billed nothing.
	meter = _meter(subscription, resource_type)
	if not meter:
		return None
	month = _month_of(month)
	closed = _closed_months(meter, keep_open=month if drafting else None)
	for _ in range(MONTHS_AHEAD):
		if month not in closed and not _is_billed(meter, month):
			return _write_month(meter, month, closed)
		closed.add(month)
		month = _next_month(month)
	frappe.logger("billing").warning(f"Usage of {subscription} has no open month before {month}")
	return None


def rollup_key(service: str, resource_id: str, month: datetime.date) -> str:
	return f"{service}::{resource_id}::{month:%Y-%m}"


def _recount_encoded(encoded: str) -> MonthCount | None:
	subscription, resource_type, month = encoded.split(_SEPARATOR)
	return recount_month(subscription, resource_type, month)


def _meter(subscription: str, resource_type: str):
	"""What a subscription's days of one resource type are counted with."""
	meter = frappe.db.get_value(
		DOCTYPE,
		{"subscription": subscription, "resource_type": resource_type},
		["service", "unit", "aggregation"],
		as_dict=True,
	)
	if not meter:
		return None
	owner = frappe.db.get_value(
		"Subscription", subscription, ["team", "cluster", "service_subject"], as_dict=True
	)
	return frappe._dict(
		meter,
		subscription=subscription,
		resource_type=resource_type,
		team=owner.team,
		cluster=owner.cluster,
		subject=owner.service_subject,
	)


def _write_month(meter, month: datetime.date, closed: set) -> MonthCount | None:
	"""Count the month's own unbilled days and the late days of closed months into its rollup."""
	days = [day for day in _unbilled_days(meter, month) if _month_of(day.day) in (closed | {month})]
	key = ingest_rollup(
		{
			"idempotency_key": rollup_key(meter.service, meter.subject, month),
			"resource_id": meter.subject,
			"resource_type": meter.resource_type,
			"meter_type": "Gauge" if meter.aggregation == LEVEL else "Counter",
			"team": meter.team,
			"cluster": meter.cluster,
			"currency": get_team_currency(meter.team),
			"period_start": month,
			"period_end": _month_end(month),
			"quantity": sum(_weight(day) for day in days),
			"unit": meter.unit,
		}
	)
	if not key:
		return None
	rollup = live_rollup(frappe.db.get_value("Usage Rollup", {"idempotency_key": key}, "name"))
	return MonthCount(month, rollup, [day.name for day in days])


def _unbilled_days(meter, month: datetime.date) -> list:
	"""Locked, so a draft bills the values it read and a concurrent writer waits for it."""
	day = frappe.qb.DocType(DOCTYPE)
	return (
		frappe.qb.from_(day)
		.select(day.name, day.day, day.quantity, day.aggregation)
		.where(
			(day.subscription == meter.subscription)
			& (day.resource_type == meter.resource_type)
			& day.invoice.isnull()
			& (day.day <= _month_end(month))
		)
		.for_update()
	).run(as_dict=True)


def _is_billed(meter, month: datetime.date) -> bool:
	"""Whether an invoice billed the month. Locks its rollup, so a draft cannot bill it meanwhile."""
	key = rollup_key(meter.service, meter.subject, month)
	name = frappe.db.get_value("Usage Rollup", {"idempotency_key": key}, "name", for_update=True)
	if not name:
		return False
	return bool(frappe.db.get_value("Usage Rollup", live_rollup(name), "invoice", for_update=True))


def _closed_months(meter, keep_open: datetime.date | None) -> set[datetime.date]:
	"""Months of this subject that an invoice billed, or that the team's draft has run for."""
	# Any outcome but a failure closes the month, so a day that lands after it goes on the next one.
	billed = frappe.get_all(
		"Usage Rollup",
		filters={
			"resource_id": meter.subject,
			"resource_type": meter.resource_type,
			"invoice": ["is", "set"],
		},
		pluck="period_start",
	)
	drafted = frappe.get_all(
		"Billing Run Team",
		filters={"team": meter.team, "outcome": ["!=", FAILED]},
		pluck="period_end",
	)
	return {_month_of(on) for on in billed} | ({_month_of(on) for on in drafted} - {keep_open})


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


def _month_of(on) -> datetime.date:
	return frappe.utils.getdate(on).replace(day=1)


def _next_month(month: datetime.date) -> datetime.date:
	return _month_end(month) + datetime.timedelta(days=1)


def _weight(day) -> float:
	"""A Level day counts as its peak over the days in its own month; a Sum day as its total."""
	quantity = frappe.utils.flt(day.quantity)
	if day.aggregation != LEVEL:
		return quantity
	on = frappe.utils.getdate(day.day)
	return quantity / calendar.monthrange(on.year, on.month)[1]


def _month_end(month: datetime.date) -> datetime.date:
	return month.replace(day=calendar.monthrange(month.year, month.month)[1])
