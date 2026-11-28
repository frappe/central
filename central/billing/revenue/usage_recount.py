# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import calendar
import datetime
from dataclasses import dataclass, field

import frappe
from frappe.query_builder import Case

from central.billing.doctype.billing_profile.billing_profile import get_team_currency
from central.billing.doctype.billing_run_team.billing_run_team import FAILED
from central.billing.platform.jobs import each_isolated
from central.billing.revenue import usage_corrections, usage_fold, usage_month
from central.billing.revenue.exchange_rates import fix_month_rate
from central.billing.revenue.metering import metered_plan_for, rollup_terms
from central.billing.revenue.rollup_updates import recounted_allowance, rerated
from central.billing.revenue.usage_month import DOCTYPE, month_of
from central.billing.revenue.usage_rating import billable_above_bundle, day_weight

WATERMARK = "usage_recount_watermark"
PAGE_SIZE = 200
# Past this many billed months, the recount stops and logs a warning.
MONTHS_AHEAD = 24
_SEPARATOR = "|"


@dataclass
class MonthCount:
	"""One usage month as a recount wrote it: the row that carries its rating and the days it counted."""

	month: datetime.date
	carrier: str
	days: dict[str, int]
	quantity: float


@dataclass
class Counted:
	"""The rated month rows, the days as a mask per month row, and the corrections that a draft billed."""

	months: list[str] = field(default_factory=list)
	days: dict[str, int] = field(default_factory=dict)
	corrections: usage_corrections.Corrections = field(default_factory=usage_corrections.Corrections)

	def add(self, written: MonthCount) -> None:
		self.months.append(written.carrier)
		for name, mask in written.days.items():
			self.days[name] = self.days.get(name, 0) | mask


def recount_changed(now=None) -> int:
	"""Hourly: recompute the monthly figure of every subscription whose days changed since the last run."""
	from central.billing.revenue.invoicing.run import billing_queue

	now = frappe.utils.get_datetime(now) if now else frappe.utils.now_datetime()
	usage_fold.fold_stragglers()
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
	month = month_of(period_end)
	counted = Counted()
	for subscription, resource_type, dimension in _unbilled_meters(team, period_end):
		written = recount_month(subscription, resource_type, month, drafting=True, dimension=dimension)
		# A month below zero bills nothing. Its days stay unbilled, so the credit goes into the next month.
		if written and written.month == month and written.quantity >= 0:
			counted.add(written)
	counted.corrections = usage_corrections.rate_open(team)
	return counted


def stamp_invoice(counted: Counted, invoice: str, team: str) -> None:
	"""Mark the months, days and corrections the invoice billed."""
	if counted.months:
		table = frappe.qb.DocType(DOCTYPE)
		# What the line billed: the quantity above the allowance, never below zero.
		billed = Case().when(table.quantity > table.locked_allowance, table.quantity - table.locked_allowance)
		(
			frappe.qb.update(table)
			.set(table.invoice, invoice)
			.set(table.billed_quantity, billed.else_(0))
			.where(table.name.isin(counted.months) & table.invoice.isnull())
		).run()
	usage_month.stamp_days(counted.days, invoice)
	usage_corrections.stamp(counted.corrections, invoice, team)


def release_invoice(invoice: str) -> None:
	"""Unmark what a cancelled invoice billed, so the invoice that replaces it bills it again."""
	table = frappe.qb.DocType(DOCTYPE)
	(
		frappe.qb.update(table)
		.set(table.invoice, None)
		.set(table.billed_quantity, 0)
		.where(table.invoice == invoice)
	).run()
	team, created = frappe.db.get_value("Invoice", invoice, ["team", "creation"])
	usage_month.release_days(invoice, team, created)
	usage_corrections.release(invoice, team)


def recount_month(
	subscription: str, resource_type: str, month, drafting: bool = False, dimension: str = ""
) -> MonthCount | None:
	"""Write the first open month at or after `month` from the days not yet billed."""
	# A billed or closed month is never recounted, so its late days go into the next open month.
	# The month a draft is billing stays open, even when an earlier draft of it billed nothing.
	meter = _meter(subscription, resource_type, dimension)
	if not meter:
		return None
	month = month_of(month)
	drafted = month if drafting else None
	closed = _closed_months(meter, keep_open=drafted)
	for _ in range(MONTHS_AHEAD):
		if month not in closed and not _is_billed(meter, month):
			return _write_month(meter, month, closed, final=month == drafted)
		closed.add(month)
		month = _next_month(month)
	frappe.logger("billing").warning(f"Usage of {subscription} has no open month before {month}")
	return None


def _recount_encoded(encoded: str) -> MonthCount | None:
	# The dimension is last and may itself hold the separator.
	subscription, resource_type, month, dimension = encoded.split(_SEPARATOR, 3)
	return recount_month(subscription, resource_type, month, dimension=dimension)


def _meter(subscription: str, resource_type: str, dimension: str = ""):
	"""What a subscription's days of one resource type and dimension are counted with."""
	meter = frappe.db.get_value(
		DOCTYPE,
		{"subscription": subscription, "resource_type": resource_type, "dimension": dimension},
		["service", "meter", "unit", "aggregation", "subject"],
		as_dict=True,
		order_by="month desc",
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
		day_subject=meter.subject,
		subscription=subscription,
		resource_type=resource_type,
		team=owner.team,
		cluster=owner.cluster,
		# A server's backup bucket bills on the server's own subscription.
		subject=owner.service_subject or owner.server_id,
		on_server=not owner.service_subject and bool(owner.server_id),
		dimension=dimension,
		cost_currency=cost_currency,
	)


def _write_month(meter, month: datetime.date, closed: set, final: bool) -> MonthCount | None:
	"""Count the month's own unbilled days and the late days of closed months onto its rated row."""
	rows = usage_month.locked_meter_months(meter.subscription, meter.resource_type, meter.dimension, month)
	days = [day for row in rows for day in row.get_open_days() if month_of(day.day) in (closed | {month})]
	currency = get_team_currency(meter.team)
	quantity = sum(day_weight(day) for day in days)
	counted = {
		**_bundle(meter, days, quantity),
		"resource_id": meter.subject,
		"resource_type": meter.resource_type,
		"team": meter.team,
		"cluster": meter.cluster,
		"currency": currency,
		"quantity": quantity,
		"locked_terms": _cost_terms(meter, currency, month, final),
	}
	carrier = usage_month.carrier_of(meter, month)
	if not _rate(carrier, counted):
		return None
	masks: dict[str, int] = {}
	for day in days:
		masks[day.month_row] = masks.get(day.month_row, 0) | usage_month.bit(day.number)
	return MonthCount(month, carrier.name, masks, quantity)


def _rate(carrier, counted: dict) -> str | None:
	"""Rate the month on its row and return the row, or None when there are no terms to bill it at."""
	now = frappe.utils.now_datetime()
	if not carrier.counted_at:
		terms = rollup_terms(counted)
		if not terms:
			return None
		updates = {
			"currency": terms["currency"],
			"cluster": terms["cluster"],
			"locked_allowance": terms["allowance"],
			"locked_rate": terms["rate"],
			"rate_date": terms.get("rate_date"),
			"resource_id": counted["resource_id"],
		}
	else:
		# An operator's corrected allowance outranks the recount's.
		updates = {
			**rerated(carrier, counted["locked_terms"]),
			**recounted_allowance(counted, is_corrected=bool(carrier.terms_corrected)),
		}
	updates.update(quantity=counted["quantity"], counted_at=now)
	frappe.db.set_value(DOCTYPE, carrier.name, updates, update_modified=False)
	return carrier.name


def _is_billed(meter, month: datetime.date) -> bool:
	"""Whether an invoice billed the month. Locks its rows, so a draft cannot bill it meanwhile."""
	table = frappe.qb.DocType(DOCTYPE)
	billed = (
		frappe.qb.from_(table)
		.select(table.name)
		.where(
			(table.subscription == meter.subscription)
			& (table.resource_type == meter.resource_type)
			& (table.dimension == meter.dimension)
			& (table.month == month)
			& table.invoice.isnotnull()
		)
		.for_update()
	).run()
	return bool(billed)


def _closed_months(meter, keep_open: datetime.date | None) -> set[datetime.date]:
	"""Months of this subject that an invoice billed, or that the team's draft has run for."""
	# Any outcome but a failure closes the month, so a day that lands after it goes on the next one.
	billed = frappe.get_all(
		DOCTYPE,
		filters={
			"subscription": meter.subscription,
			"resource_type": meter.resource_type,
			"invoice": ["is", "set"],
		},
		pluck="month",
	)
	drafted = frappe.get_all(
		"Billing Run Team",
		filters={"team": meter.team, "outcome": ["!=", FAILED]},
		pluck="period_end",
	)
	return {month_of(on) for on in billed} | ({month_of(on) for on in drafted} - {keep_open})


def _changed_months(since, now) -> set[str]:
	table = frappe.qb.DocType(DOCTYPE)
	rows = (
		frappe.qb.from_(table)
		.select(table.subscription, table.resource_type, table.month, table.dimension)
		.distinct()
		.where(
			(table.changed_at > since)
			& (table.changed_at <= now)
			& table.resource_type.isnotnull()
			& (table.open_days != 0)
		)
	).run()
	return {
		_SEPARATOR.join((subscription, resource_type, f"{frappe.utils.getdate(on):%Y-%m-01}", dimension))
		for subscription, resource_type, on, dimension in rows
	}


def _unbilled_meters(team: str, period_end) -> set[tuple]:
	table = frappe.qb.DocType(DOCTYPE)
	return set(
		(
			frappe.qb.from_(table)
			.select(table.subscription, table.resource_type, table.dimension)
			.distinct()
			.where(
				(table.team == team)
				& (table.open_days != 0)
				& (table.month <= month_of(period_end))
				& table.resource_type.isnotnull()
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


def _next_month(month: datetime.date) -> datetime.date:
	return _month_end(month) + datetime.timedelta(days=1)


def _bundle(meter, days: list, quantity: float) -> dict:
	"""The month's bundle as the rollup's allowance, or nothing where its terms set the allowance."""
	# A meter that records a daily bundle is billed by it, by design: it replaces a plan's
	# monthly allowance, so a plan that ran part of the month or changed mid-month bills its days.
	if any(frappe.utils.flt(day.included) for day in days):
		return {"counted_allowance": quantity - billable_above_bundle(days, quantity)}
	# A live-priced server meter has no allowance of its own, and one that has carried a daily
	# bundle was billed by it, so a bundle gone to none clears either.
	if meter.on_server and (_is_live(meter.resource_type) or _has_carried_bundle(meter)):
		return {"counted_allowance": 0}
	return {}


def _has_carried_bundle(meter) -> bool:
	"""Whether any day of the meter, billed or not, recorded a bundle."""
	return bool(
		frappe.db.exists(
			DOCTYPE,
			{
				"subscription": meter.subscription,
				"resource_type": meter.resource_type,
				"dimension": meter.dimension,
				"carries_bundle": 1,
			},
		)
	)


def _is_live(resource_type: str) -> bool:
	"""Whether the resource's metered family reads its rate live."""
	plan = metered_plan_for(resource_type)
	return bool(plan and plan.pricing_mode == "Live")


def _month_end(month: datetime.date) -> datetime.date:
	return month.replace(day=calendar.monthrange(month.year, month.month)[1])
