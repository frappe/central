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
from central.billing.revenue.exchange_rates import fix_month_rate
from central.billing.revenue.metering import ingest_rollup, live_rollup
from central.billing.revenue.usage_ledger import DOCTYPE, LEVEL

WATERMARK = "usage_recount_watermark"
PAGE_SIZE = 200
# Past this many months with a billed rollup, the recount stops and logs a warning.
MONTHS_AHEAD = 24
_SEPARATOR = "|"
# Usage Rollup.idempotency_key is a Data field.
MAXIMUM_ROLLUP_KEY = 140
_KEY_JOIN = "::"


@dataclass
class MonthCount:
	"""One usage month as a recount wrote it."""

	month: datetime.date
	rollup: str
	days: list[str]
	quantity: float


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
	for subscription, resource_type, dimension in _unbilled_meters(team, period_end):
		written = recount_month(subscription, resource_type, month, drafting=True, dimension=dimension)
		# A month below zero bills nothing. Its days stay unbilled, so the credit goes into the next month.
		if written and written.month == month and written.quantity >= 0:
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


def recount_month(
	subscription: str, resource_type: str, month, drafting: bool = False, dimension: str = ""
) -> MonthCount | None:
	"""Write the first open month at or after `month` from the days not yet billed."""
	# A billed or closed month is never recounted, so its late days go into the next open month.
	# The month a draft is billing stays open, even when an earlier draft of it billed nothing.
	meter = _meter(subscription, resource_type, dimension)
	if not meter:
		return None
	month = _month_of(month)
	drafted = month if drafting else None
	closed = _closed_months(meter, keep_open=drafted)
	for _ in range(MONTHS_AHEAD):
		if month not in closed and not _is_billed(meter, month):
			return _write_month(meter, month, closed, final=month == drafted)
		closed.add(month)
		month = _next_month(month)
	frappe.logger("billing").warning(f"Usage of {subscription} has no open month before {month}")
	return None


def rollup_key(service: str, resource_id: str, month: datetime.date, dimension: str = "") -> str:
	key = _KEY_JOIN.join((service, resource_id, f"{month:%Y-%m}"))
	return _KEY_JOIN.join((key, dimension)) if dimension else key


def dimension_room(service: str, resource_id: str) -> int:
	"""The longest dimension a rollup key of this subject has room for."""
	return MAXIMUM_ROLLUP_KEY - len(rollup_key(service, resource_id, datetime.date.today())) - len(_KEY_JOIN)


def _recount_encoded(encoded: str) -> MonthCount | None:
	# The dimension is last and may itself hold the separator.
	subscription, resource_type, month, dimension = encoded.split(_SEPARATOR, 3)
	return recount_month(subscription, resource_type, month, dimension=dimension)


def _meter(subscription: str, resource_type: str, dimension: str = ""):
	"""What a subscription's days of one resource type and dimension are counted with."""
	meter = frappe.db.get_value(
		DOCTYPE,
		{"subscription": subscription, "resource_type": resource_type, "dimension": dimension},
		["service", "meter", "unit", "aggregation"],
		as_dict=True,
	)
	if not meter:
		return None
	cost_currency = frappe.db.get_value(
		"Service Meter", {"parent": meter.service, "meter_key": meter.meter}, "cost_currency"
	)
	owner = frappe.db.get_value(
		"Subscription", subscription, ["team", "cluster", "service_subject", "server_id"], as_dict=True
	)
	return frappe._dict(
		meter,
		subscription=subscription,
		resource_type=resource_type,
		team=owner.team,
		cluster=owner.cluster,
		# A server's backup bucket bills on the server's own subscription.
		subject=owner.service_subject or owner.server_id,
		dimension=dimension,
		cost_currency=cost_currency,
	)


def _write_month(meter, month: datetime.date, closed: set, final: bool) -> MonthCount | None:
	"""Count the month's own unbilled days and the late days of closed months into its rollup."""
	days = [day for day in _unbilled_days(meter, month) if _month_of(day.day) in (closed | {month})]
	currency = get_team_currency(meter.team)
	terms = _cost_terms(meter, currency, month, final)
	quantity = sum(_weight(day) for day in days)
	key = ingest_rollup(
		{
			**_bundle(days, quantity),
			"idempotency_key": rollup_key(meter.service, meter.subject, month, meter.dimension),
			"resource_id": meter.subject,
			"resource_type": meter.resource_type,
			"dimension": meter.dimension,
			"meter_type": "Gauge" if meter.aggregation == LEVEL else "Counter",
			"team": meter.team,
			"cluster": meter.cluster,
			"currency": currency,
			"period_start": month,
			"period_end": _month_end(month),
			"quantity": quantity,
			"unit": meter.unit,
			"locked_terms": terms,
		}
	)
	if not key:
		return None
	rollup = live_rollup(frappe.db.get_value("Usage Rollup", {"idempotency_key": key}, "name"))
	return MonthCount(month, rollup, [day.name for day in days], quantity)


def _unbilled_days(meter, month: datetime.date) -> list:
	"""Locked, so a draft bills the values it read and a concurrent writer waits for it."""
	day = frappe.qb.DocType(DOCTYPE)
	return (
		frappe.qb.from_(day)
		.select(day.name, day.day, day.quantity, day.included, day.aggregation)
		.where(
			(day.subscription == meter.subscription)
			& (day.resource_type == meter.resource_type)
			& (day.dimension == meter.dimension)
			& day.invoice.isnull()
			& (day.written_off == 0)
			& (day.day <= _month_end(month))
		)
		.for_update()
	).run(as_dict=True)


def _is_billed(meter, month: datetime.date) -> bool:
	"""Whether an invoice billed the month. Locks its rollup, so a draft cannot bill it meanwhile."""
	key = rollup_key(meter.service, meter.subject, month, meter.dimension)
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
		.select(day.subscription, day.resource_type, day.day, day.dimension)
		.distinct()
		.where(
			(day.landed_at > since)
			& (day.landed_at <= now)
			& day.resource_type.isnotnull()
			& (day.written_off == 0)
		)
	).run()
	return {
		_SEPARATOR.join((subscription, resource_type, f"{frappe.utils.getdate(on):%Y-%m-01}", dimension))
		for subscription, resource_type, on, dimension in rows
	}


def _unbilled_meters(team: str, period_end) -> set[tuple]:
	day = frappe.qb.DocType(DOCTYPE)
	return set(
		(
			frappe.qb.from_(day)
			.select(day.subscription, day.resource_type, day.dimension)
			.distinct()
			.where(
				(day.team == team)
				& day.invoice.isnull()
				& (day.written_off == 0)
				& (day.day <= period_end)
				& day.resource_type.isnotnull()
			)
		).run()
	)


def _cost_terms(meter, currency: str, month: datetime.date, final: bool) -> frappe._dict | None:
	"""A meter that counts money bills that amount, converted at the month's rate, with no allowance."""
	if not meter.cost_currency:
		return None
	found = fix_month_rate(meter.cost_currency, currency, month, final=final)
	return frappe._dict(
		team=meter.team,
		cluster=meter.cluster,
		currency=currency,
		allowance=0,
		rate=found.rate,
		rate_date=found.rate_date if found.fixed else None,
		is_converted=meter.cost_currency != currency,
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
	return quantity / _days_in_month(day.day)


def _bundle(days: list, quantity: float) -> dict:
	"""The month's bundle as the rollup's allowance, when any day had one."""
	if not any(frappe.utils.flt(day.included) for day in days):
		return {}
	# Rewritten with each recount, as the month's days and their bundles change.
	return {"counted_allowance": quantity - _billable(days, quantity)}


def _billable(days: list, quantity: float) -> float:
	"""The month's quantity above the bundle: each Level day above its own, a Sum month above its share."""
	if all(day.aggregation == LEVEL for day in days):
		return sum(
			max(0.0, frappe.utils.flt(day.quantity) - frappe.utils.flt(day.included))
			/ _days_in_month(day.day)
			for day in days
		)
	# A Sum meter writes a day for each day its plan ran, so the bundle scales with those days.
	share = sum(frappe.utils.flt(day.included) / _days_in_month(day.day) for day in days)
	return max(0.0, quantity - share)


def _days_in_month(on) -> int:
	on = frappe.utils.getdate(on)
	return calendar.monthrange(on.year, on.month)[1]


def _month_end(month: datetime.date) -> datetime.date:
	return month.replace(day=calendar.monthrange(month.year, month.month)[1])
