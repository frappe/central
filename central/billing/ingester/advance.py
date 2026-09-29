# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Push each wallet top-up to the accounting system as an advance, GST included.

Money received before the service is an advance, and GST on it is due as it
arrives. When an invoice later uses the wallet, the invoice uses this advance.
"""

import frappe
from frappe import _

from central.billing.ingester import connection, gst
from central.billing.ingester.settings import accounting_settings

PENDING_BATCH = 100


def enqueue_sync(entry: str) -> None:
	"""Queue the advance for a top-up credit, once the credit commits."""
	if not connection.enabled():
		return
	frappe.enqueue(
		"central.billing.ingester.advance.sync_advance",
		queue="short",
		job_id=f"advance-sync::{entry}",
		deduplicate=True,
		enqueue_after_commit=True,
		entry=entry,
	)


def sync_advance(entry: str) -> str | None:
	"""Background job: make sure this top-up has its advance. Returns the advance id."""
	from central.billing.ingester.customer import ensure_customer

	credit = frappe.get_doc("Credit Ledger Entry", entry)
	if credit.advance_id or not credit.gateway_payment_id:
		return credit.advance_id

	gateway, payment_id = _split_payment_id(credit.gateway_payment_id)
	existing = connection.find(
		"Payment Entry", [["reference_no", "=", payment_id], ["docstatus", "=", 1]], ["name"]
	)
	if existing:
		# Pushed before, but the answer was lost. Adopt it rather than book it twice.
		credit.db_set("advance_id", existing[0].name, update_modified=False)
		return existing[0].name

	customer = ensure_customer(credit.team)
	if not customer:
		frappe.throw(_("Team {0} has no customer in the accounting system yet.").format(credit.team))
	advance = connection.post("api/resource/Payment Entry", _payload(credit, customer, gateway, payment_id))
	credit.db_set("advance_id", advance.name, update_modified=False)
	return advance.name


def sync_pending_advances() -> None:
	"""Daily: queue every top-up whose advance never made it."""
	if not connection.enabled():
		return
	for entry in frappe.get_all(
		"Credit Ledger Entry",
		filters=[["gateway_payment_id", "is", "set"], ["advance_id", "is", "not set"]],
		pluck="name",
		order_by="creation asc",
		limit=PENDING_BATCH,
	):
		enqueue_sync(entry)


def _payload(credit, customer: str, gateway: str, payment_id: str) -> dict:
	settings = accounting_settings()
	route = _gateway_row(settings, gateway, credit.currency)
	tax = gst.treatment(credit.team)
	date = frappe.utils.getdate(credit.created_at or credit.creation)
	return {
		"doctype": "Payment Entry",
		"docstatus": 1,
		"naming_series": settings.series_receipt_voucher,
		"payment_type": "Receive",
		"company": settings.company,
		"posting_date": str(date),
		"party_type": "Customer",
		"party": customer,
		# Named here because the accounting system does not always move it there itself.
		"paid_from": settings.advance_account,
		"paid_to": route.clearing_account,
		"paid_amount": credit.amount,
		"received_amount": credit.amount,
		"mode_of_payment": route.mode_of_payment,
		"reference_no": payment_id,
		"reference_date": str(date),
		"company_address": settings.company_address,
		"company_gstin": gst.company_gstin(),
		"customer_address": frappe.db.get_value("Billing Profile", credit.team, "address_id"),
		"billing_address_gstin": tax.gstin,
		"gst_category": tax.gst_category,
		"place_of_supply": tax.place_of_supply,
		"taxes": gst.tax_rows(tax.template, paid_amount=credit.amount),
		"remarks": f"Wallet top-up {credit.name} ({payment_id})",
	}


def _gateway_row(settings, gateway: str, currency: str):
	for row in settings.gateways:
		if row.gateway == gateway and row.currency == currency:
			return row
	frappe.throw(_("Billing Settings has no {0} {1} row under Gateway Accounts.").format(gateway, currency))


def _split_payment_id(stored: str) -> tuple[str, str]:
	"""`Stripe:pi_123` into its gateway and the gateway's own payment id."""
	gateway, _sep, payment_id = stored.partition(":")
	if not payment_id:
		frappe.throw(_("Top-up {0} does not say which gateway took it.").format(stored))
	return gateway, payment_id
