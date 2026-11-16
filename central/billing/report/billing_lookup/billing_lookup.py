# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import escape_html, flt
from frappe.utils.translations import _lt

from central.billing.authz import require_operator
from central.billing.doctype.billing_profile.billing_profile import get_missing_field_labels
from central.billing.doctype.invoice.invoice import OVERDUE, UNSETTLED
from central.billing.payments import collection_mode
from central.billing.report.billing_lookup import subscriptions
from central.billing.report.billing_lookup.layout import column
from central.billing.revenue import credits

EVENTS = "Billing Events"
METHODS = "Payment Methods"
INVOICES = "Open Invoices"
SUBSCRIPTIONS = "Subscriptions"
CHANGES = "Subscription Changes"
EVENT_LIMIT = 20
# What happened to the money an event records. An event with an amount and no entry
# here shows as unexplained, in red, so a new kind cannot pass unnoticed.
MONEY_MEANING = {
	"Invoice Generated": _lt("Billed to the customer"),
	"Invoice Issued": _lt("Billed, collection started"),
	"Invoice Held": _lt("Billed, not sent yet"),
	"Invoice Paid": _lt("Paid to us"),
	"Invoice Waived": _lt("Waived, not collected"),
	"Top-up Order Credited": _lt("Added to the customer's wallet"),
	"Refund Pending": _lt("Refund sent, waiting for the bank"),
	"Refund Completed": _lt("Refunded to the customer"),
	"Refund Failed": _lt("Refund not sent"),
	"Payment Attempt Refunded": _lt("Refunded to the customer"),
}
UNEXPLAINED_MONEY = _lt("Not explained, check the record")
# Methods that cannot be charged; a Cancelled one was removed on purpose and is left out.
UNUSABLE_METHODS = ("Failed", "Expired", "Pending Validation", "Paused")


def execute(filters: dict | None = None):
	require_operator()
	filters = frappe._dict(filters or {})
	if not filters.team:
		return [], [], _("Pick a team to see its billing.")
	columns, rows = VIEWS.get(filters.view, _events)(filters.team)
	return columns, rows, None, None, _summary(filters.team)


def _events(team: str) -> tuple[list, list]:
	rows = frappe.get_all(
		"Billing Event",
		filters={"team": team},
		fields=[
			"occurred_at",
			"event_type",
			"subject_doctype",
			"subject",
			"amount",
			"currency",
			"outcome",
			"reason",
		],
		order_by="occurred_at desc",
		limit=EVENT_LIMIT,
	)
	for row in rows:
		row.money_meaning = _money_meaning(row)
		row.money_unexplained = flt(row.amount) and row.event_type not in MONEY_MEANING
		row.amount = row.amount or None
	return [
		column(_("When"), "occurred_at", "Datetime", 170),
		column(_("Event"), "event_type", "Data", 220),
		column(_("Record Type"), "subject_doctype", "Link", 140, options="DocType"),
		column(_("Record"), "subject", "Dynamic Link", 170, options="subject_doctype"),
		column(_("Amount"), "amount", "Currency", 120, options="currency"),
		column(_("What Happened to the Money"), "money_meaning", "Data", 230),
		column(_("Outcome"), "outcome", "Data", 100),
		column(_("Reason"), "reason", "Data", 320),
	], rows


def _money_meaning(event) -> str | None:
	if not flt(event.amount):
		return None
	return str(MONEY_MEANING.get(event.event_type, UNEXPLAINED_MONEY))


def _methods(team: str) -> tuple[list, list]:
	rows = frappe.get_all(
		"Payment Method",
		filters={"team": team, "status": ["!=", "Cancelled"]},
		fields=[
			"name",
			"display_label",
			"method_type",
			"gateway",
			"status",
			"is_default",
			"last_failed_at",
			"failure_reason",
			"decline_code",
		],
		order_by="is_default desc, priority asc, creation desc",
	)
	for row in rows:
		row.failure_reason = row.failure_reason or row.decline_code
	return [
		column(_("Payment Method"), "name", "Link", 140, options="Payment Method"),
		column(_("Label"), "display_label", "Data", 180),
		column(_("Type"), "method_type", "Data", 100),
		column(_("Gateway"), "gateway", "Link", 110, options="Payment Gateway"),
		column(_("Status"), "status", "Data", 140),
		column(_("Default"), "is_default", "Check", 80),
		column(_("Last Failed At"), "last_failed_at", "Datetime", 170),
		column(_("Last Failure"), "failure_reason", "Data", 300),
	], rows


def _invoices(team: str) -> tuple[list, list]:
	rows = _open_invoices(team)
	for row in rows:
		row.still_owed = flt(row.total) - flt(row.amount_paid)
	return [
		column(_("Invoice"), "name", "Link", 170, options="Invoice"),
		column(_("Status"), "status", "Data", 110),
		column(_("Held For"), "hold_reason", "Data", 140),
		column(_("Still Owed"), "still_owed", "Currency", 130, options="currency"),
		column(_("Due On"), "due_date", "Date", 110),
		column(_("Period Start"), "period_start", "Date", 110),
		column(_("Period End"), "period_end", "Date", 110),
		column(_("Currency"), "currency", "Link", 90, options="Currency"),
	], rows


VIEWS = {
	EVENTS: _events,
	SUBSCRIPTIONS: subscriptions.running,
	CHANGES: subscriptions.changes,
	METHODS: _methods,
	INVOICES: _invoices,
}


def _open_invoices(team: str) -> list[dict]:
	"""Unsettled invoices, held drafts included; a held draft has no due date yet."""
	return frappe.get_all(
		"Invoice",
		filters={"team": team, "status": ["in", UNSETTLED]},
		fields=[
			"name",
			"status",
			"hold_reason",
			"total",
			"amount_paid",
			"currency",
			"due_date",
			"period_start",
			"period_end",
		],
		order_by="period_end asc",
	)


def _summary(team: str) -> list[dict]:
	invoices = _open_invoices(team)
	return [
		_profile_card(team),
		*_collection_cards(team),
		*subscriptions.monthly_cost_cards(team),
		*_owed_cards(invoices),
		_count_card(_("Held Invoices"), sum(1 for i in invoices if i.hold_reason), "orange"),
		_count_card(
			_("Methods That Cannot Be Charged"),
			frappe.db.count("Payment Method", {"team": team, "status": ["in", UNUSABLE_METHODS]}),
			"red",
		),
		*_wallet_cards(team),
	]


def _profile_card(team: str) -> dict:
	missing = get_missing_field_labels(team)
	value = _("Missing {0}").format(", ".join(missing)) if missing else _("Complete")
	return _card(_("Billing Profile"), value, "red" if missing else "green")


def _collection_cards(team: str) -> list[dict]:
	status = collection_mode.status(team)
	mode = status["collection_mode"]
	method = status["charged_method"]
	return [
		_card(_("Collection Mode"), mode, "orange" if mode in collection_mode.DEBIT_HELD_MODES else "blue"),
		_card(_("Charged First"), method or _("No method to charge"), "blue" if method else "red"),
	]


def _owed_cards(invoices: list[dict]) -> list[dict]:
	"""What the team owes on issued invoices, one card per currency. A held draft is not owed yet."""
	owed: dict[str, float] = {}
	overdue: set[str] = set()
	for i in (i for i in invoices if i.due_date):
		owed[i.currency] = owed.get(i.currency, 0.0) + flt(i.total) - flt(i.amount_paid)
		if i.status == OVERDUE:
			overdue.add(i.currency)
	if not owed:
		return [_card(_("Owed"), _("Nothing"), "green")]
	return [
		{
			"label": _("Owed ({0})").format(currency),
			"value": amount,
			"datatype": "Currency",
			"currency": currency,
			"indicator": "red" if currency in overdue else "orange",
		}
		for currency, amount in sorted(owed.items())
	]


def _wallet_cards(team: str) -> list[dict]:
	return [
		{
			"label": _("Wallet ({0})").format(w.currency),
			"value": w.balance,
			"datatype": "Currency",
			"currency": w.currency,
			"indicator": "blue",
		}
		for w in credits.get_balances(team)
	]


def _count_card(label: str, count: int, problem_color: str) -> dict:
	return {
		"label": label,
		"value": count,
		"datatype": "Int",
		"indicator": problem_color if count else "green",
	}


def _card(label: str, value: str, indicator: str) -> dict:
	return {"label": label, "value": escape_html(value), "datatype": "Data", "indicator": indicator}
