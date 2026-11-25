# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""How a Central invoice was paid, recorded against its Sales Invoice: the card payment
and the promotional credit."""

import frappe

from central.billing.ingester import connection
from central.billing.ingester.settings import accounting_settings, receivable_account


def card_attempt(inv):
	"""The captured card or UPI payment that settled this invoice, if one did."""
	from central.billing.payments.refunds import late_captured_attempts

	if frappe.utils.flt(inv.amount_paid) <= 0:
		return None
	filters = {"invoice": inv.name, "status": "Captured"}
	if late := late_captured_attempts(inv.name):
		filters["name"] = ["not in", late]  # captured after the invoice was paid; never in the books
	name = frappe.db.get_value("Payment Attempt", filters, "name", order_by="creation desc")
	return frappe.get_doc("Payment Attempt", name) if name else None


def record_card_payment(inv, customer: str) -> str | None:
	"""A Payment Entry against the Sales Invoice for what the card paid. Found if it exists."""
	attempt = card_attempt(inv)
	if not attempt:
		return None
	existing = connection.find(
		"Payment Entry",
		[["reference_no", "=", attempt.gateway_transaction_id], ["docstatus", "=", 1]],
		["name"],
	)
	if existing:
		return existing[0].name

	settings = accounting_settings()
	route = _gateway_row(settings, attempt.gateway, attempt.currency)
	if attempt.currency != inv.currency:
		raise RuntimeError(f"{inv.name} is in {inv.currency} but was paid in {attempt.currency}")
	sales_invoice = connection.fetch("Sales Invoice", inv.erpnext_invoice)
	# What the card took, capped at what is outstanding.
	owed = min(frappe.utils.flt(attempt.amount), frappe.utils.flt(sales_invoice.outstanding_amount))
	# The receivable and the clearing account are both in the invoice's currency.
	rate = frappe.utils.flt(sales_invoice.conversion_rate) or 1
	payload = {
		"doctype": "Payment Entry",
		"docstatus": 1,
		"payment_type": "Receive",
		"company": settings.company,
		"posting_date": frappe.utils.nowdate(),
		"party_type": "Customer",
		"party": customer,
		"paid_from": sales_invoice.debit_to,
		"paid_to": route.clearing_account,
		"paid_amount": owed,
		"received_amount": owed,
		"source_exchange_rate": rate,
		"target_exchange_rate": rate,
		"mode_of_payment": route.mode_of_payment,
		"reference_no": attempt.gateway_transaction_id,
		"reference_date": str(frappe.utils.getdate(attempt.completed_at or attempt.creation)),
		"references": [
			{
				"reference_doctype": "Sales Invoice",
				"reference_name": inv.erpnext_invoice,
				"allocated_amount": owed,
			}
		],
		"remarks": f"{attempt.gateway} payment {attempt.gateway_transaction_id} for {marker(inv)}",
	}
	return connection.post("api/resource/Payment Entry", payload).name


def promotional_journal(inv, customer: str, against: str, amount: float, marker: str, reverse=False) -> str:
	"""Settle (or, with `reverse`, unsettle) promotional credit against a Sales Invoice or credit note.

	Found by `marker` if it was made before.
	"""
	existing = connection.find("Journal Entry", [["cheque_no", "=", marker], ["docstatus", "=", 1]], ["name"])
	if existing:
		return existing[0].name
	settings = accounting_settings()
	if not settings.promotional_credit_account:
		raise RuntimeError("Billing Settings has no promotional credit account")
	document = connection.fetch("Sales Invoice", against) or {}
	rate = frappe.utils.flt(document.get("conversion_rate")) or 1
	expense = {
		"account": settings.promotional_credit_account,
		"cost_center": settings.cost_center,
		"exchange_rate": 1,
	}
	party = {
		"account": document.get("debit_to") or receivable_account(inv.currency),
		"party_type": "Customer",
		"party": customer,
		"exchange_rate": rate,
		"reference_type": "Sales Invoice",
		"reference_name": against,
	}
	if reverse:
		expense["credit_in_account_currency"] = frappe.utils.flt(amount * rate, 2)
		party["debit_in_account_currency"] = amount
	else:
		expense["debit_in_account_currency"] = frappe.utils.flt(amount * rate, 2)
		party["credit_in_account_currency"] = amount
	return connection.post(
		"api/resource/Journal Entry",
		{
			"doctype": "Journal Entry",
			"docstatus": 1,
			"voucher_type": "Journal Entry",
			"company": settings.company,
			"posting_date": frappe.utils.nowdate(),
			"cheque_no": marker,
			"cheque_date": frappe.utils.nowdate(),
			"multi_currency": int(rate != 1),
			"user_remark": f"Promotional credit {'given back' if reverse else 'used'} on Central invoice {inv.name}",
			"accounts": [expense, party],
		},
	).name


def _gateway_row(settings, gateway: str, currency: str):
	for row in settings.gateways:
		if row.gateway == gateway and row.currency == currency:
			return row
	raise RuntimeError(f"Billing Settings has no {gateway} {currency} row under Gateway Accounts")


def marker(inv) -> str:
	"""The text that ties a record in the accounting system to its Central invoice."""
	return f"Central invoice {inv.name}"
