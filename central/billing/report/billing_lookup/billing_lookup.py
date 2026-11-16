# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import escape_html, flt

from central.billing.authz import require_operator
from central.billing.doctype.billing_profile.billing_profile import get_missing_field_labels
from central.billing.doctype.invoice.invoice import OVERDUE, UNSETTLED
from central.billing.payments import collection_mode
from central.billing.revenue import credits

EVENTS = "Billing Events"
METHODS = "Payment Methods"
INVOICES = "Open Invoices"
EVENT_LIMIT = 20
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
	return [
		_column(_("When"), "occurred_at", "Datetime", 170),
		_column(_("Event"), "event_type", "Data", 220),
		_column(_("Record Type"), "subject_doctype", "Link", 140, options="DocType"),
		_column(_("Record"), "subject", "Dynamic Link", 170, options="subject_doctype"),
		_column(_("Money Moved"), "amount", "Currency", 120, options="currency"),
		_column(_("Outcome"), "outcome", "Data", 100),
		_column(_("Reason"), "reason", "Data", 320),
	], rows


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
		_column(_("Payment Method"), "name", "Link", 140, options="Payment Method"),
		_column(_("Label"), "display_label", "Data", 180),
		_column(_("Type"), "method_type", "Data", 100),
		_column(_("Gateway"), "gateway", "Link", 110, options="Payment Gateway"),
		_column(_("Status"), "status", "Data", 140),
		_column(_("Default"), "is_default", "Check", 80),
		_column(_("Last Failed At"), "last_failed_at", "Datetime", 170),
		_column(_("Last Failure"), "failure_reason", "Data", 300),
	], rows


def _invoices(team: str) -> tuple[list, list]:
	rows = _open_invoices(team)
	for row in rows:
		row.still_owed = flt(row.total) - flt(row.amount_paid)
	return [
		_column(_("Invoice"), "name", "Link", 170, options="Invoice"),
		_column(_("Status"), "status", "Data", 110),
		_column(_("Held For"), "hold_reason", "Data", 140),
		_column(_("Still Owed"), "still_owed", "Currency", 130, options="currency"),
		_column(_("Due On"), "due_date", "Date", 110),
		_column(_("Period Start"), "period_start", "Date", 110),
		_column(_("Period End"), "period_end", "Date", 110),
		_column(_("Currency"), "currency", "Link", 90, options="Currency"),
	], rows


VIEWS = {EVENTS: _events, METHODS: _methods, INVOICES: _invoices}


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


def _column(label: str, fieldname: str, fieldtype: str, width: int, options: str | None = None) -> dict:
	column = {"label": label, "fieldname": fieldname, "fieldtype": fieldtype, "width": width}
	if options:
		column["options"] = options
	return column
