# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import datetime
import json
from dataclasses import dataclass, field

import frappe
from frappe import _

from central.billing.catalog.pricing import get_catalog_rates, resolve_rate
from central.billing.platform.invariants import Violation
from central.billing.platform.jobs import each_isolated
from central.billing.revenue.metered_lines import MAXIMUM_DESCRIPTION
from central.billing.revenue.metering import metered_plan_for
from central.billing.revenue.usage_month import BILLED, CORRECTION, CREDIT_DUE, DAY_FIELDS, DOCTYPE, OPEN
from central.billing.states import transition

# A correction is billed only within this many days of the invoice that billed its day.
WINDOW_DAYS = 90
CREDITED = "Credited"
WRITTEN_OFF = "Written Off"
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
	"""Rate the team's open corrections in their window: a line for each that raises the bill, Credit Due for the rest."""
	rated = Corrections()
	months: dict[tuple, BilledMonth | None] = {}
	for correction in _open_corrections(team, frappe.utils.getdate(today)):
		invoice = _slots(correction.slots).get(str(correction.day), {}).get("invoice")
		# A day a cancelled invoice gave back is billed again with its own value first.
		if not invoice:
			continue
		key = (invoice, correction.subscription, correction.resource_type, correction.dimension)
		if key not in months:
			months[key] = BilledMonth.load(*key)
		if months[key] is None:
			frappe.logger("billing").warning(f"Correction {correction.name} has no rated month to bill at")
			continue
		_rate(months[key], correction, team, rated)
	return rated


def stamp(corrections: Corrections, invoice: str, team: str) -> None:
	"""Mark the corrections the invoice billed."""
	for name in corrections.names:
		_move(name, BILLED, team, reason=invoice, invoice=invoice)


def release(invoice: str, team: str) -> None:
	"""Reopen the corrections a cancelled invoice billed, so the invoice that replaces it bills them again."""
	for name in frappe.get_all(CORRECTION, filters={"invoice": invoice, "status": BILLED}, pluck="name"):
		_move(name, OPEN, team, reason=f"{invoice} was cancelled", invoice=None)


def mark_credited(name: str, reason: str) -> None:
	"""Record that an operator issued the credit note a Credit Due correction asked for."""
	correction = frappe.get_doc(CORRECTION, name, for_update=True)
	team = frappe.db.get_value(DOCTYPE, correction.parent, "team")
	_move(name, CREDITED, team, reason=reason)
	frappe.get_doc(DOCTYPE, correction.parent).add_comment(
		"Info", f"Correction of day {correction.day} credited: {reason}"
	)


def write_off_expired(today=None) -> int:
	"""Daily: write off each open correction that no invoice billed within its window."""
	cutoff = frappe.utils.getdate(today) - datetime.timedelta(days=WINDOW_DAYS)
	written, after = 0, ""
	while page := _expired_page(cutoff, after):
		written += len(each_isolated("Usage correction write-off", CORRECTION, page, _write_off))
		after = page[-1]
	return written


def check_credit_due_corrections() -> list[Violation]:
	"""Every lower value for a billed day has had its credit note issued by an operator.

	Issue the credit note for the difference, then mark the correction Credited."""
	correction = frappe.qb.DocType(CORRECTION)
	month = frappe.qb.DocType(DOCTYPE)
	rows = (
		frappe.qb.from_(correction)
		.join(month)
		.on(correction.parent == month.name)
		.select(
			correction.name,
			correction.day,
			correction.billed_value,
			correction.value,
			month.name.as_("month_row"),
			month.team,
			month.subject,
			month.month,
		)
		.where(correction.status == CREDIT_DUE)
		.orderby(correction.name)
		.limit(200)
	).run(as_dict=True)
	return [
		Violation(
			check="M4",
			team=row.team,
			subject_doctype=DOCTYPE,
			subject=row.month_row,
			detail=f"{row.subject} on {_day_of(row):%d %b %Y}: billed {row.billed_value}, now {row.value}. Issue the credit note, then mark correction {row.name} Credited.",
		)
		for row in rows
	]


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
		from central.billing.revenue.usage_recount import billable_above_bundle, day_weight

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
		self.days[key].billed = value


def _rate(month: BilledMonth, correction, team: str, rated: Corrections) -> None:
	"""Bill a correction that raises the bill at its month's terms; mark one that does not Credit Due."""
	key = (correction.month_row, correction.day)
	delta = month.get_delta(key, frappe.utils.flt(correction.value))
	frappe.db.set_value(CORRECTION, correction.name, "billable_delta", delta, update_modified=False)
	if delta <= 0:
		_move(correction.name, CREDIT_DUE, team, reason="the new value does not raise the bill")
		return
	# Later corrections of the same month are weighed against this one, as the invoice bills them together.
	month.apply(key, frappe.utils.flt(correction.value))
	rated.lines.append(_line(month.carrier, correction, delta))
	rated.names.append(correction.name)


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
		"charge_date": _day_of(correction),
		"amount": frappe.utils.flt(delta * rate, 2),
	}


def get_description(correction) -> str:
	"""The line text: what was corrected, the day, and the report it replaces with the one that corrected it."""
	day = _day_of(correction)
	subject = " ".join(part for part in (correction.subject, correction.dimension) if part)
	text = _("Correction · {0} · {1} · report {2} → {3}")
	parts = (f"{day.day} {day:%b %Y}", correction.original_report or "-", correction.report or "-")
	# The day and the reports are kept whole; a long subject gives way.
	room = MAXIMUM_DESCRIPTION - len(text.format("", *parts))
	return text.format(subject[: max(room, 0)], *parts)


def _open_corrections(team: str, today: datetime.date) -> list[frappe._dict]:
	"""The team's open corrections still in their window, oldest day first, locked with their month rows."""
	correction = frappe.qb.DocType(CORRECTION)
	month = frappe.qb.DocType(DOCTYPE)
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
		)
		.where(
			(month.team == team)
			& (correction.status == OPEN)
			& (correction.billed_invoice_date >= today - datetime.timedelta(days=WINDOW_DAYS))
		)
		.orderby(month.name)
		.orderby(correction.day)
		.orderby(correction.idx)
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
	days = {}
	for row in rows:
		for number, slot in _slots(row.slots).items():
			if slot.get("invoice") != invoice:
				continue
			first = frappe.utils.flt(row[DAY_FIELDS[int(number) - 1]])
			days[(row.name, int(number))] = frappe._dict(
				day=row.month.replace(day=int(number)),
				aggregation=row.aggregation,
				included=frappe.utils.flt(slot.get("included")),
				first=first,
				billed=first,
			)
	for correction in _billed_corrections(list({name for name, _day in days})):
		if (key := (correction.parent, correction.day)) in days:
			days[key].billed = frappe.utils.flt(correction.value)
	return days


def _billed_corrections(rows: list[str]) -> list[frappe._dict]:
	"""The billed corrections of these month rows, in the order they were made, so the latest wins."""
	if not rows:
		return []
	return frappe.get_all(
		CORRECTION,
		filters={"parent": ["in", rows], "parenttype": DOCTYPE, "status": BILLED},
		fields=["parent", "day", "value"],
		order_by="idx asc",
	)


def _expired_page(cutoff: datetime.date, after: str) -> list[str]:
	return frappe.get_all(
		CORRECTION,
		filters={"status": OPEN, "billed_invoice_date": ["<", cutoff], "name": [">", after]},
		order_by="name asc",
		limit=PAGE_SIZE,
		pluck="name",
	)


def _write_off(name: str) -> None:
	correction = frappe.get_doc(CORRECTION, name, for_update=True)
	if correction.status != OPEN:
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


def _day_of(row) -> datetime.date:
	return frappe.utils.getdate(row.month).replace(day=frappe.utils.cint(row.day))


def _slots(value) -> dict:
	if isinstance(value, dict):
		return value
	return json.loads(value) if value else {}
