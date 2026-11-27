# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import datetime
from dataclasses import dataclass, field

import frappe
from frappe import _
from frappe.query_builder import Case

from central.billing.catalog.pricing import get_catalog_rates, resolve_rate
from central.billing.platform.jobs import each_isolated
from central.billing.revenue.metered_lines import MAXIMUM_DESCRIPTION
from central.billing.revenue.metering import metered_plan_for
from central.billing.revenue.usage_month import (
	BILLED,
	BILLED_BY_HAND,
	CORRECTION,
	CREDIT_DUE,
	CREDITED,
	DAY_FIELDS,
	DOCTYPE,
	NO_CHARGE,
	OPEN,
	SETTLED,
	WRITTEN_OFF,
	billed_value,
)
from central.billing.revenue.usage_month_days import billed_days_of, invoice_of_day
from central.billing.revenue.usage_month_rows import corrections_of
from central.billing.revenue.usage_rating import billable_above_bundle, day_weight
from central.billing.states import transition

# A correction is billed only within this many days of the invoice that billed its day.
# A lower value is still rated after it: the window limits what we charge, never a credit we owe.
WINDOW_DAYS = 90
PAGE_SIZE = 500
_CARRIER_FIELDS = (
	"name",
	"month",
	"quantity",
	"locked_allowance",
	"locked_rate",
	"terms_corrected",
	"resource_id",
	"resource_type",
	"dimension",
	"cluster",
	"unit",
	"currency",
)


@dataclass
class Corrections:
	"""The adjustment lines a draft adds, and the corrections they bill."""

	lines: list[dict] = field(default_factory=list)
	names: list[str] = field(default_factory=list)


def rate_open(team: str, today=None) -> Corrections:
	"""Rate the team's open corrections: a line for each in its window that raises the bill, Credit Due or No Charge for the rest."""
	rated = Corrections()
	pending = _with_months(_open_corrections(team, frappe.utils.getdate(today)))
	# Falls settle first, so a rise is rated against settled values only and bills the same on
	# every draft until an invoice stamps it, even when a draft is not stamped or is reissued.
	for month, correction in sorted(pending, key=lambda pair: _is_rise(*pair)):
		_rate(month, correction, team, rated)
	return rated


def stamp(corrections: Corrections, invoice: str, team: str) -> None:
	"""Mark the corrections the invoice billed."""
	for name in corrections.names:
		_move(name, BILLED, team, reason=invoice, invoice=invoice)


def release(invoice: str, team: str) -> None:
	"""Give back the corrections a cancelled invoice billed, so the invoice that replaces it bills the true day."""
	billed = frappe.get_all(
		CORRECTION, filters={"invoice": invoice, "status": BILLED}, fields=["name", "parent", "idx", "day"]
	)
	by_row = corrections_of(list({correction.parent for correction in billed}))
	given_back = {correction.name for correction in billed}
	for correction in billed:
		# Another correction of the day billed on this invoice is given back too, so it replaced nothing.
		day = [
			c
			for c in by_row.get(correction.parent, [])
			if c.day == correction.day and (c.name == correction.name or c.name not in given_back)
		]
		_release_one(correction, day, f"{invoice} was cancelled", team)


def _release_one(correction, day: list, reason: str, team: str) -> None:
	"""Reopen a given-back correction, or write it off when a later value of its day replaced it."""
	later = [c for c in day if frappe.utils.cint(c.idx) > frappe.utils.cint(correction.idx)]
	if not any(c.status in SETTLED for c in later):
		_move(correction.name, OPEN, team, reason=reason, invoice=None)
		_unmark_replaced(correction, day)
		return
	if any(c.status in (BILLED, CREDITED, BILLED_BY_HAND) for c in later):
		# A later charge or credit note was rated against this value and money moved on it, so
		# nothing is re-rated; keeping the invoice marks it for an operator (readiness M7).
		_move(correction.name, WRITTEN_OFF, team, reason=f"{reason}; a later value was rated against it")
		return
	# Nothing was charged or credited against this value: write it off, and rate the later values
	# again against what the day bills without it.
	_move(correction.name, WRITTEN_OFF, team, reason=f"{reason}; a later value replaced it", invoice=None)
	_rerate(later, _value_before(correction, day), reason, team)
	_unmark_replaced(correction, day)


def _rerate(later: list, baseline: float, reason: str, team: str) -> None:
	"""Rate the day's latest value again against `baseline`, and close the ones in between."""
	live = [c for c in later if c.status in (CREDIT_DUE, NO_CHARGE, OPEN)]
	if not live:
		return
	# Only the latest value is what the day bills; rating each in between would bill a rise and
	# owe back a fall that cancel out, and leave a credit note for an operator to issue.
	for c in live[:-1]:
		_move(
			c.name, WRITTEN_OFF, team, reason=f"{reason}; a later value of the day replaced it", invoice=None
		)
	latest = live[-1]
	if latest.status == OPEN:
		frappe.db.set_value(CORRECTION, latest.name, "billed_value", baseline, update_modified=False)
	else:
		_move(latest.name, OPEN, team, reason=reason, billed_value=baseline)


def _unmark_replaced(correction, day: list) -> None:
	"""Clear the readiness M7 marker of earlier written-off values the day is now rated again without."""
	earlier = [c for c in day if frappe.utils.cint(c.idx) < frappe.utils.cint(correction.idx)]
	for c in reversed(earlier):
		# A settled value is the baseline the day is rated against, so values before it stay as they are.
		if c.status in SETTLED:
			return
		if c.status == WRITTEN_OFF and c.invoice:
			# The next draft rates the day from below this value, so it bills what this value added.
			frappe.db.set_value(CORRECTION, c.name, "invoice", None, update_modified=False)
			frappe.get_doc(DOCTYPE, correction.parent).add_comment(
				"Info",
				f"Correction of day {c.day} to {c.value}, billed on {c.invoice} and reissued, is billed "
				"again by the next draft, so it no longer needs billing by hand.",
			)


def _value_before(correction, day: list) -> float:
	"""What the day billed before this correction: the latest settled one made before it, else its slot."""
	earlier = [c for c in day if frappe.utils.cint(c.idx) < frappe.utils.cint(correction.idx)]
	first = frappe.db.get_value(DOCTYPE, correction.parent, DAY_FIELDS[correction.day - 1])
	return billed_value(earlier, correction.day, frappe.utils.flt(first))


def mark_credited(name: str, reason: str) -> None:
	"""Record that an operator issued the credit note a Credit Due correction asked for."""
	correction = frappe.get_doc(CORRECTION, name, for_update=True)
	team = frappe.db.get_value(DOCTYPE, correction.parent, "team")
	_move(name, CREDITED, team, reason=reason)
	frappe.get_doc(DOCTYPE, correction.parent).add_comment(
		"Info", f"Correction of day {correction.day} credited: {reason}"
	)


def mark_billed_by_hand(name: str, reason: str) -> None:
	"""Record that an operator billed by hand what a reissued correction added."""
	correction = frappe.get_doc(CORRECTION, name, for_update=True)
	if correction.status != WRITTEN_OFF or not correction.invoice:
		frappe.throw(
			_("Only a correction a reissue left for billing by hand can be marked billed by hand."),
			frappe.ValidationError,
		)
	team = frappe.db.get_value(DOCTYPE, correction.parent, "team")
	_move(name, BILLED_BY_HAND, team, reason=reason)
	frappe.get_doc(DOCTYPE, correction.parent).add_comment(
		"Info", f"Correction of day {correction.day} billed by hand: {reason}"
	)


def write_off_expired(today=None) -> int:
	"""Daily: write off each open charge that no invoice billed within its window."""
	cutoff = frappe.utils.getdate(today) - datetime.timedelta(days=WINDOW_DAYS)
	written, after = 0, ""
	while page := _expired_page(cutoff, after):
		written += len(each_isolated("Usage correction write-off", CORRECTION, page, _write_off))
		after = page[-1]
	return written


class BilledMonth:
	"""What one invoice billed for one meter: the terms of its rated month and the value it billed for each day."""

	def __init__(self, carrier, days: dict):
		self.carrier = carrier
		self.days = days

	@classmethod
	def load(cls, invoice: str, subscription: str, resource_type: str, dimension: str):
		meter = {"subscription": subscription, "resource_type": resource_type, "dimension": dimension}
		carrier = frappe.db.get_value(
			DOCTYPE,
			{**meter, "invoice": invoice, "counted_at": ["is", "set"]},
			list(_CARRIER_FIELDS),
			as_dict=True,
		)
		if not carrier:
			return None
		carrier.rate = _billed_rate(carrier, invoice)
		return cls(carrier, _billed_days(invoice, meter, carrier.month))

	def get_billable(self, changed: tuple | None = None) -> float:
		"""The month's billable quantity with the billed values, and with `changed` = (day key, value) applied."""
		days = [
			frappe._dict(day, quantity=changed[1] if changed and key == changed[0] else day.billed)
			for key, day in self.days.items()
		]
		# The rated quantity already holds every day's first value, and carried credit with it.
		quantity = frappe.utils.flt(self.carrier.quantity) + sum(
			day_weight(day) - day_weight(frappe._dict(day, quantity=day.first)) for day in days
		)
		if not self.carrier.terms_corrected and any(frappe.utils.flt(day.included) for day in days):
			return billable_above_bundle(days, quantity)
		return max(0.0, quantity - frappe.utils.flt(self.carrier.locked_allowance))

	def get_delta(self, key: tuple, value: float) -> float:
		"""What a new value for one day adds to the billable quantity."""
		if key not in self.days:
			return 0.0
		return self.get_billable((key, value)) - self.get_billable()

	def apply(self, key: tuple, value: float) -> None:
		"""Rate later corrections against the month with this day's new value in it."""
		if key in self.days:
			self.days[key].billed = value


def _with_months(corrections: list) -> list[tuple]:
	"""Each correction with the billed month it is rated against, in day order."""
	pending, months = [], {}
	for correction in corrections:
		invoice = invoice_of_day(correction, correction.day)
		# A day a cancelled invoice gave back is billed again with its own value first.
		if not invoice:
			continue
		key = (invoice, correction.subscription, correction.resource_type, correction.dimension)
		if key not in months:
			months[key] = BilledMonth.load(*key)
		if months[key] is None:
			frappe.logger("billing").warning(f"Correction {correction.name} has no rated month to bill at")
			continue
		pending.append((months[key], correction))
	return pending


def _is_rise(month: BilledMonth, correction) -> bool:
	"""Whether a correction is above what its day bills now."""
	day = month.days.get((correction.month_row, correction.day))
	return bool(day) and frappe.utils.flt(correction.value) > frappe.utils.flt(day.billed)


def _rate(month: BilledMonth, correction, team: str, rated: Corrections) -> None:
	"""Bill a correction that raises the bill at its month's terms; close one that lowers it or changes nothing."""
	key = (correction.month_row, correction.day)
	delta = month.get_delta(key, frappe.utils.flt(correction.value))
	frappe.db.set_value(CORRECTION, correction.name, "billable_delta", delta, update_modified=False)
	# Float noise from summing day weights must not bill, or credit, a zero change.
	rounded = frappe.utils.flt(delta, frappe.get_precision(CORRECTION, "billable_delta"))
	if rounded > 0 and not correction.billable:
		# Past its window a charge is not billed; write_off_expired closes it.
		return
	# A credit owed or a value rated as no change sets the month too, so the next correction is rated against it.
	month.apply(key, frappe.utils.flt(correction.value))
	if rounded < 0:
		_move(correction.name, CREDIT_DUE, team, reason="the new value lowers the bill")
	elif rounded == 0:
		_close_unchanged(correction, team)
	else:
		rated.lines.append(_line(month.carrier, correction, delta))
		rated.names.append(correction.name)


def _close_unchanged(correction, team: str) -> None:
	"""Close a correction that stays inside the bundle or allowance: no line, nothing to credit."""
	reason = "the new value stays inside the bundle or allowance, so the bill does not change"
	_move(correction.name, NO_CHARGE, team, reason=reason)
	frappe.get_doc(DOCTYPE, correction.month_row).add_comment(
		"Info",
		f"Correction of day {correction.day} to {correction.value} (report {correction.report}) "
		f"needs no invoice line: {reason}.",
	)


def _billed_rate(carrier, invoice: str) -> float:
	"""The rate the invoice billed the month at: its locked rate, or for a live-priced family the rate on its line."""
	plan = metered_plan_for(carrier.resource_type)
	if not (plan and plan.pricing_mode == "Live"):
		return frappe.utils.flt(carrier.locked_rate)
	filters = {
		"parent": invoice,
		"subscription_resource": carrier.resource_id,
		"resource_type": carrier.resource_type,
		# A correction line names the day it corrects; the month's own line does not.
		"charge_date": ["is", "not set"],
	}
	if carrier.dimension:
		filters["description"] = ["like", f"{carrier.dimension[:MAXIMUM_DESCRIPTION]}%"]
	billed = frappe.db.get_value("Invoice Line Item", filters, "rate")
	if billed is not None:
		return frappe.utils.flt(billed)
	# A month inside its allowance had no line; today's rate is the one it would have billed at.
	return frappe.utils.flt(
		resolve_rate(get_catalog_rates("Plan", plan.name), carrier.currency, carrier.cluster)
	)


def _line(carrier, correction, delta: float) -> dict:
	rate = carrier.rate
	return {
		"subscription_resource": carrier.resource_id,
		"plan": None,
		"cluster": carrier.cluster,
		"resource_type": carrier.resource_type,
		"dimension": carrier.dimension,
		"unit": carrier.unit,
		"description": get_description(correction),
		"quantity": delta,
		"rate": rate,
		"days": 0,
		"charge_date": get_day_of(correction),
		"amount": frappe.utils.flt(delta * rate, 2),
	}


def get_description(correction) -> str:
	"""The line text: what was corrected, the day, and the report it replaces with the one that corrected it."""
	day = get_day_of(correction)
	subject = " ".join(part for part in (correction.subject, correction.dimension) if part)
	text = _("Correction · {0} · {1} · report {2} → {3}")
	parts = (f"{day.day} {day:%b %Y}", correction.original_report or "-", correction.report or "-")
	# The day and the reports are kept whole; a long subject gives way.
	room = MAXIMUM_DESCRIPTION - len(text.format("", *parts))
	return text.format(subject[: max(room, 0)], *parts)


def _open_corrections(team: str, today: datetime.date) -> list[frappe._dict]:
	"""The team's open corrections in their window, and lower values past it, oldest day first, locked with their month rows."""
	correction = frappe.qb.DocType(CORRECTION)
	month = frappe.qb.DocType(DOCTYPE)
	in_window = correction.billed_invoice_date >= today - datetime.timedelta(days=WINDOW_DAYS)
	return (
		frappe.qb.from_(correction)
		.join(month)
		.on(correction.parent == month.name)
		.select(
			correction.name,
			correction.day,
			correction.value,
			correction.original_report,
			correction.report,
			month.name.as_("month_row"),
			month.month,
			month.subject,
			month.subscription,
			month.resource_type,
			month.dimension,
			month.slots,
			Case().when(in_window, 1).else_(0).as_("billable"),
		)
		.where(
			(month.team == team)
			& (correction.status == OPEN)
			& (in_window | (correction.value < correction.billed_value))
		)
		.orderby(month.name)
		.orderby(correction.day)
		.orderby(correction.idx)
		.orderby(correction.creation)
		# A writer replaces an open correction under its month row's lock.
		.for_update()
	).run(as_dict=True)


def _billed_days(invoice: str, meter: dict, month) -> dict[tuple, frappe._dict]:
	"""Each day the invoice billed for the meter, with its first value and the value last billed for it."""
	rows = frappe.get_all(
		DOCTYPE,
		filters={**meter, "month": ["<=", month], "billed": ["!=", 0]},
		fields=["name", "month", "aggregation", "slots", *DAY_FIELDS],
	)
	corrections = corrections_of([row.name for row in rows])
	return {
		(row.name, day): _billed_day(row, day, slot, corrections.get(row.name, []))
		for row, day, slot in billed_days_of(rows, invoice)
	}


def _billed_day(row, day: int, slot: dict, corrections: list) -> frappe._dict:
	first = frappe.utils.flt(row[DAY_FIELDS[day - 1]])
	return frappe._dict(
		day=row.month.replace(day=day),
		aggregation=row.aggregation,
		included=frappe.utils.flt(slot.get("included")),
		first=first,
		billed=billed_value(corrections, day, first),
	)


def _expired_page(cutoff: datetime.date, after: str) -> list[str]:
	"""Open charges past their window; a lower value is never written off, as its credit is still owed."""
	correction = frappe.qb.DocType(CORRECTION)
	return (
		frappe.qb.from_(correction)
		.select(correction.name)
		.where(
			(correction.status == OPEN)
			& (correction.billed_invoice_date < cutoff)
			& (correction.value > correction.billed_value)
			& (correction.name > after)
		)
		.orderby(correction.name)
		.limit(PAGE_SIZE)
	).run(pluck=True)


def _write_off(name: str) -> None:
	correction = frappe.get_doc(CORRECTION, name, for_update=True)
	if correction.status != OPEN or correction.value <= correction.billed_value:
		return
	month = frappe.get_doc(DOCTYPE, correction.parent)
	_move(name, WRITTEN_OFF, month.team, reason="no invoice billed it within its window")
	day = month.month.replace(day=correction.day)
	month.add_comment(
		"Info",
		f"Correction of {day:%d %b %Y} written off: {correction.billed_value} to {correction.value} "
		f"(report {correction.original_report} to {correction.report}). No invoice billed it within "
		f"{WINDOW_DAYS} days of {correction.billed_invoice_date}, the date of the invoice that billed the day.",
	)


def _move(name: str, status: str, team: str | None, reason: str, **values) -> None:
	"""Move a correction through its state machine and save it with `values`."""
	correction = frappe.get_doc(CORRECTION, name)
	# A child row has no team of its own; the event is filed under its month row's team.
	correction.team = team
	transition(correction, status, reason=reason)
	correction.update(values)
	correction.db_update()


def get_day_of(row) -> datetime.date:
	"""The date of a correction's day."""
	return frappe.utils.getdate(row.month).replace(day=frappe.utils.cint(row.day))
