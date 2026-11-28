# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import add_days, add_months, flt, getdate, today

from central.billing.doctype.invoice.invoice import UNSETTLED, owed_filters
from central.billing.report._economics import BilledMonth, to_inr
from central.billing.report._inventory import FUNDING_CLASSES, PAID, Inventory
from central.billing.report._revenue import is_revenue
from central.billing.revenue.credits import credit_lots
from central.billing.revenue.tax import internal_teams

EXPIRY_WINDOWS = (30, 60)
TOP_CUSTOMERS = 5
INVOICE_FIELDS = (
	"team",
	"status",
	"currency",
	"subtotal",
	"amount_paid",
	"credit_applied",
	"advance_applied",
	"expected_collection",
	"hold_reason",
)


def month_figures(month=None) -> dict:
	"""The figures of the month that holds the date `month`, else of the last closed month, for the Money Update.

	Each figure reuses code a billing report runs: BilledMonth (Service Profitability), the
	month's invoices, credit_lots, owed_filters (AR Aging) and Inventory (Unit Economics).
	Money is INR at the month's report rate. Credit, collections and margins read today's state."""
	billed = BilledMonth({"month": month} if month else {})
	previous = BilledMonth({"month": add_months(billed.start, -1)})
	internal = internal_teams()
	invoices = _invoices(billed.start)
	return {
		"month": str(billed.start),
		"headline": headline(billed, invoices, internal),
		"previous": headline(previous, _invoices(previous.start), internal),
		"customers": customers(billed, invoices, internal),
		"credit": credit(internal),
		"collections": collections(),
		"services": services(billed, internal),
		"margins": margins(Inventory()),
	}


def headline(billed: BilledMonth, invoices: list, internal: set) -> dict:
	"""Billed revenue, and how the month's invoices were paid, held or waived."""
	figures = {"billed": sum((flt(line.revenue_inr) for line in billed.lines), 0.0)}
	figures.update(dict.fromkeys(("cash_collected", "paid_by_free_credit", "held", "waived"), 0.0))
	figures["held_invoices"] = 0
	for invoice in invoices:
		_add_invoice(figures, invoice, internal, billed.start)
	figures["unpriced_usd"] = any(line.revenue_inr is None for line in billed.lines)
	return _rounded(figures)


def _add_invoice(figures: dict, invoice, internal: set, month) -> None:
	if invoice.status == "Waived":
		figures["waived"] += _inr(invoice.subtotal, invoice.currency, month)
		return
	if not is_revenue(invoice.status, invoice.team, internal):
		return
	advance = flt(invoice.advance_applied)
	figures["cash_collected"] += _inr(flt(invoice.amount_paid) + advance, invoice.currency, month)
	figures["paid_by_free_credit"] += _inr(flt(invoice.credit_applied) - advance, invoice.currency, month)
	if invoice.hold_reason:
		figures["held"] += _inr(invoice.expected_collection, invoice.currency, month)
		figures["held_invoices"] += 1


def customers(billed: BilledMonth, invoices: list, internal: set) -> dict:
	"""Who paid cash this month, who paid for the first time, and how much of revenue the largest teams bring."""
	payers = {
		invoice.team
		for invoice in invoices
		if is_revenue(invoice.status, invoice.team, internal)
		and flt(invoice.amount_paid) + flt(invoice.advance_applied) > 0
	}
	return {
		"paying": len(payers),
		"first_payments": len(payers - _paid_before(payers, billed.start)),
		"with_payment_method": _teams_with_a_payment_method(internal),
		"payment_success_percent": _payment_success(billed.start, billed.end),
		"top_customers_share_percent": _top_customers_share(billed),
	}


def credit(internal: set) -> dict:
	"""Credit left in customers' wallets: bought, free, and free credit that expires soon."""
	figures = {"bought_left": 0.0, "free_left": 0.0}
	figures.update({f"free_expiring_in_{days}_days": 0.0 for days in EXPIRY_WINDOWS})
	on_free_credit = set()
	for wallet in frappe.get_all("Credit Wallet", filters={"balance": [">", 0]}, fields=["team", "currency"]):
		if wallet.team not in internal and _add_wallet(figures, wallet):
			on_free_credit.add(wallet.team)
	figures["teams_on_free_credit"] = len(on_free_credit)
	return _rounded(figures)


def _add_wallet(figures: dict, wallet) -> float:
	"""Add one wallet's lots to `figures` and return its free credit left."""
	bought, free = [], []
	for lot in credit_lots(wallet.team, wallet.currency):
		if _is_spendable(lot):
			(bought if lot.paid_in else free).append(lot)
	free_left = sum(lot.remaining for lot in free)
	figures["bought_left"] += _inr(sum(lot.remaining for lot in bought), wallet.currency)
	figures["free_left"] += _inr(free_left, wallet.currency)
	for days in EXPIRY_WINDOWS:
		figures[f"free_expiring_in_{days}_days"] += _inr(_expiring_within(free, days), wallet.currency)
	return free_left


def _expiring_within(lots: list, days: int) -> float:
	until = getdate(add_days(today(), days))
	return sum(lot.remaining for lot in lots if lot.expires_on and getdate(lot.expires_on) <= until)


def _is_spendable(lot) -> bool:
	return lot.remaining > 0 and (not lot.expires_on or getdate(lot.expires_on) >= getdate())


def collections() -> dict:
	"""What customers owe now, what is overdue or held, and how many mandates need a new consent."""
	owed = frappe.get_all(
		"Invoice",
		filters=[*owed_filters(), ["expected_collection", ">", 0]],
		fields=["currency", "expected_collection", "due_date"],
	)
	overdue = [invoice for invoice in owed if getdate(invoice.due_date) < getdate()]
	return _rounded(
		{
			"outstanding": sum(_inr(i.expected_collection, i.currency) for i in owed),
			"overdue": sum(_inr(i.expected_collection, i.currency) for i in overdue),
			"overdue_invoices": len(overdue),
			"invoices_on_hold": frappe.db.count(
				"Invoice", {"status": ["in", UNSETTLED], "hold_reason": ["is", "set"]}
			),
			"mandates_to_reauthorise": frappe.db.count(
				"Payment Method", {"status": "Active", "reauth_required": 1}
			),
		}
	)


def services(billed: BilledMonth, internal: set) -> dict:
	"""Revenue, cost and customers per service, and bundled plans against metered usage."""
	by_service, pricing = {}, {"bundled": _empty_group(), "unbundled": _empty_group()}
	for line in billed.lines:
		if not is_revenue(line.status, line.team, internal):
			continue
		_add_line(by_service.setdefault(line.service, _empty_group()), line)
		_add_line(pricing["bundled" if line.resource_type == "bundle" else "unbundled"], line)
	rows = [{"service": name, **_finish_group(group)} for name, group in by_service.items()]
	return {
		"by_service": sorted(rows, key=lambda row: row["revenue"], reverse=True),
		**{name: _finish_group(group) for name, group in pricing.items()},
	}


def _empty_group() -> dict:
	return {"revenue": 0.0, "cost": 0.0, "teams": set(), "free_lines": 0}


def _add_line(group: dict, line) -> None:
	group["revenue"] += flt(line.revenue_inr)
	group["cost"] += flt(line.cost_inr)
	group["teams"].add(line.team)
	group["free_lines"] += 0 if flt(line.amount) else 1


def _finish_group(group: dict) -> dict:
	"""`free_lines` counts lines billed at 0: included in a plan, or a rate of 0."""
	customers = len(group.pop("teams"))
	return _rounded({**group, "customers": customers, "margin": group["revenue"] - group["cost"]})


def margins(inventory: Inventory) -> dict:
	"""The live servers' monthly margin at list price against the cash margin, with the gap per funding class.

	List value prices every server at its rate. Revenue counts only paying customers. Both
	carry the whole metal bill: the servers' vCPU share and the idle capacity."""
	by_funding = {funding: {"servers": 0, "cost": 0.0, "list_value": 0.0} for funding in FUNDING_CLASSES}
	for server in inventory.servers:
		row = by_funding[server.funding]
		row["servers"] += 1
		row["cost"] += server.cost
		row["list_value"] += flt(inventory.to_inr(server.list_rate, server.currency))
	idle_cost = sum(row["cost"] for row in inventory.idle_rows())
	metal_cost = idle_cost + sum(row["cost"] for row in by_funding.values())
	list_value = sum(row["list_value"] for row in by_funding.values())
	revenue = by_funding[PAID]["list_value"]
	return _rounded(
		{
			"metal_cost": metal_cost,
			"idle_cost": idle_cost,
			"list_value": list_value,
			"revenue": revenue,
			"margin_at_list": list_value - metal_cost,
			"actual_margin": revenue - metal_cost,
			"by_funding": {funding: _rounded(row) for funding, row in by_funding.items()},
		}
	)


def _invoices(month) -> list:
	return frappe.get_all(
		"Invoice",
		filters={"invoice_type": "Billable", "status": ["!=", "Cancelled"], "period_start": month},
		fields=list(INVOICE_FIELDS),
	)


def _paid_before(teams: set, month) -> set:
	"""Of `teams`, those that paid cash on an invoice of an earlier month."""
	if not teams:
		return set()
	return set(
		frappe.get_all(
			"Invoice",
			filters={
				"team": ["in", list(teams)],
				"status": "Paid",
				"amount_paid": [">", 0],
				"period_start": ["<", month],
			},
			pluck="team",
			distinct=True,
		)
	)


def _teams_with_a_payment_method(internal: set) -> int:
	teams = frappe.get_all("Payment Method", filters={"status": "Active"}, pluck="team", distinct=True)
	return len(set(teams) - internal)


def _payment_success(start, end) -> float | None:
	"""Captured attempts as a percent of the attempts made in the month, as Gateway Payment Success Ratio counts them."""
	statuses = frappe.get_all(
		"Payment Attempt",
		filters={"initiated_at": ["between", [start, add_days(end, 1)]]},
		pluck="status",
	)
	if not statuses:
		return None
	return 100 * statuses.count("Captured") / len(statuses)


def _top_customers_share(billed: BilledMonth) -> float | None:
	by_team = {}
	for line in billed.lines:
		by_team[line.team] = by_team.get(line.team, 0) + flt(line.revenue_inr)
	total = sum(by_team.values())
	if not total:
		return None
	return 100 * sum(sorted(by_team.values(), reverse=True)[:TOP_CUSTOMERS]) / total


def _inr(amount, currency: str | None, on=None) -> float:
	"""`amount` in INR. An amount with no rate counts as 0: the headline names it in `unpriced_usd`."""
	return flt(to_inr(amount, currency, on))


def _rounded(figures: dict) -> dict:
	return {key: flt(value, 2) if isinstance(value, float) else value for key, value in figures.items()}
