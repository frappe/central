# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Cancel a paid invoice, and give each part of its payment back the way it came.

The operator's request (or a lost dispute) decides and records the plan: the
invoice is cancelled and one Refund is booked per part. The work runs as a chain
of background jobs, one step each, so a step that moves money commits before the
next one starts:

  1. Wallet credit the invoice drew goes back to the wallet.
  2. Each card or UPI charge is refunded at the gateway. A charge lost to a dispute
     is not refunded; the gateway has already taken it back.
  3. The accounting system gets a credit note against the Sales Invoice.
  4. Each refund is recorded there as a payment out, against the credit note.
     Paid-in wallet credit is booked again as an advance with its GST, because the
     accounting system does not restore the GST on an advance for a credit note.
"""

import frappe
from frappe import _

from central.billing.states import transition

# CGST Act section 34: a credit note is issued by 30 November after the end of the
# financial year of the invoice.
CREDIT_NOTE_DEADLINE = (11, 30)

_UNDER_WAY = "Initiated"


def cancel_and_refund(invoice: str, reason: str, dispute: dict | None = None) -> dict:
	"""Cancel a paid invoice and book what goes back, then start the work.

	`dispute` is a lost chargeback ({id, payment_intent}): that charge is recorded as
	lost to the dispute rather than refunded.
	"""
	doc = frappe.get_doc("Invoice", invoice)
	if doc.status != "Paid":
		frappe.throw(_("Only a paid invoice can be cancelled and refunded."), frappe.ValidationError)
	_check_credit_note_deadline(doc)

	for attempt in _captured_attempts(doc.name):
		lost = dispute and attempt.gateway_transaction_id == dispute.get("payment_intent")
		_book_refund(
			doc,
			"Dispute" if lost else "Source",
			attempt.amount,
			reason,
			payment_attempt=attempt.name,
			gateway_refund_id=dispute["id"] if lost else None,
		)
	wallet = frappe.utils.flt(doc.credit_applied) + frappe.utils.flt(doc.advance_tax_applied)
	if wallet > 0:
		_book_refund(doc, "Wallet", wallet, reason)

	transition(doc, "Cancelled", reason=reason, actor=frappe.session.user)
	doc.save(ignore_permissions=True)
	doc.add_comment("Info", f"Cancelled and refunded: {reason}")
	_enqueue(invoice)
	return {"invoice": invoice, "refunds": _refunds(invoice)}


def run_cancellation(invoice: str) -> None:
	"""Background job: take the next step of this invoice's cancellation."""
	from central.billing.ingester.connection import enabled
	from central.billing.ingester.locks import hold_until_transaction_ends

	if not hold_until_transaction_ends(f"cancellation::{invoice}"):
		return  # a step is running and queues the one after
	doc = frappe.get_doc("Invoice", invoice)
	step = _next_step(doc, enabled())
	if step:
		step()
		_enqueue(invoice)


def _next_step(doc, accounting: bool):
	refunds = _refunds(doc.name)
	for refund in refunds:
		if refund.status == _UNDER_WAY:
			return lambda r=refund: _settle(doc, r)
	if not (accounting and doc.erpnext_invoice):
		return None  # nothing was issued in the accounting system
	if not doc.credit_note_id:
		return lambda: _credit_note(doc)
	for refund in refunds:
		if refund.status == "Completed" and not refund.payment_record_id and _money_to_record(doc, refund):
			return lambda r=refund: _record_payment(doc, r)
	return None


# --- step 1 and 2: Central and the gateway -------------------------------------------


def _settle(doc, refund) -> None:
	"""Give a part back: wallet credit to the wallet, a charge through its gateway."""
	refund = frappe.get_doc("Refund", refund.name)
	if refund.destination == "Wallet":
		from central.billing.revenue.invoicing.lifecycle import give_back_wallet

		give_back_wallet(doc)
		_finish(refund, "Completed")
	elif refund.destination == "Dispute":
		_finish(refund, "Completed")  # the gateway already took it back
		attempt = frappe.get_doc("Payment Attempt", refund.payment_attempt)
		transition(attempt, "Refunded", actor="dispute", correlation=doc.name, amount=refund.amount)
		attempt.save(ignore_permissions=True)
	else:
		attempt = frappe.get_doc("Payment Attempt", refund.payment_attempt)
		result = _adapter(attempt.gateway).refund(attempt, refund.amount, refund.reason or "", refund.name)
		refund.gateway_refund_id = result.gateway_refund_id
		_finish(refund, "Completed" if result.success else "Failed")
		if result.success:
			transition(attempt, "Refunded", actor="refund", correlation=doc.name, amount=refund.amount)
			attempt.save(ignore_permissions=True)
		else:
			frappe.log_error(
				title=f"Refund failed: {doc.name}",
				message=f"{attempt.gateway} refused refund {refund.name}: {result.status}",
			)


def _finish(refund, status: str) -> None:
	transition(refund, status, actor="refund", correlation=refund.invoice, amount=refund.amount)
	refund.completed_at = frappe.utils.now_datetime()
	refund.save(ignore_permissions=True)


# --- step 3 and 4: the accounting system ---------------------------------------------


def _credit_note(doc) -> None:
	"""The credit note against the Sales Invoice: found if it exists, else made."""
	from central.billing.ingester import connection
	from central.billing.ingester.settings import accounting_settings

	existing = connection.find(
		"Sales Invoice",
		[["return_against", "=", doc.erpnext_invoice], ["is_return", "=", 1], ["docstatus", "=", 1]],
		["name"],
	)
	if existing:
		doc.db_set("credit_note_id", existing[0].name)
		return
	note = connection.post(
		"api/method/erpnext.accounts.doctype.sales_invoice.mapper.make_sales_return",
		{"source_name": doc.erpnext_invoice},
	)
	note.update(
		{
			"naming_series": accounting_settings().series_credit_note,
			"advances": [],
			"docstatus": 1,
			"remarks": f"Credit note for Central invoice {doc.name}: {_reason(doc.name)}",
		}
	)
	for key in ("name", "__islocal", "__unsaved"):
		note.pop(key, None)
	doc.db_set("credit_note_id", connection.post("api/resource/Sales Invoice", note).name)


def _money_to_record(doc, refund) -> float:
	"""What of this refund left, or re-entered, the accounting system's books."""
	if refund.destination != "Wallet":
		return frappe.utils.flt(refund.amount)
	# Promotional credit never reached the books, so only paid-in credit moves there.
	return frappe.utils.flt(doc.advance_applied) + frappe.utils.flt(doc.advance_tax_applied)


def _record_payment(doc, refund) -> None:
	"""The payment out against the credit note, and for wallet credit a new advance."""
	from central.billing.ingester import connection

	refund = frappe.get_doc("Refund", refund.name)
	amount = _money_to_record(doc, refund)
	existing = connection.find(
		"Payment Entry", [["remarks", "like", f"%{refund.name}%"], ["docstatus", "=", 1]], ["name"]
	)
	payment = existing[0].name if existing else _pay_out(doc, refund, amount)
	refund.db_set("payment_record_id", payment)
	if refund.destination == "Wallet":
		refund.db_set("advance_id", _advance_again(doc, refund, amount))


def _pay_out(doc, refund, amount: float) -> str:
	"""A Payment Entry of type Pay that settles `amount` of the credit note."""
	from central.billing.ingester import connection
	from central.billing.ingester.settings import accounting_settings, wallet_clearing_account

	payment = connection.post(
		"api/method/erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
		{"dt": "Sales Invoice", "dn": doc.credit_note_id, "party_amount": amount},
	)
	if refund.destination == "Wallet":
		account, reference = wallet_clearing_account(doc.currency), refund.name
	else:
		attempt = frappe.get_doc("Payment Attempt", refund.payment_attempt)
		route = _gateway_row(accounting_settings(), attempt.gateway, attempt.currency)
		account, reference = route.clearing_account, refund.gateway_refund_id
		payment["mode_of_payment"] = route.mode_of_payment
	payment.update(
		{
			"paid_from": account,
			"reference_no": reference,
			"reference_date": frappe.utils.nowdate(),
			"docstatus": 1,
			"remarks": f"{refund.destination} refund {refund.name} for Central invoice {doc.name}",
		}
	)
	for key in ("name", "__islocal", "__unsaved"):
		payment.pop(key, None)
	return connection.post("api/resource/Payment Entry", payment).name


def _advance_again(doc, refund, amount: float) -> str:
	"""Book returned paid-in credit as an advance again, with its GST."""
	from central.billing.ingester import connection, gst
	from central.billing.ingester.settings import accounting_settings, wallet_clearing_account

	existing = connection.find(
		"Payment Entry",
		[["reference_no", "=", f"{refund.name}-advance"], ["docstatus", "=", 1]],
		["name"],
	)
	if existing:
		name = existing[0].name
	else:
		settings = accounting_settings()
		tax = gst.treatment(doc.team)
		gst_back = frappe.utils.flt(doc.advance_tax_applied)
		name = connection.post(
			"api/resource/Payment Entry",
			{
				"doctype": "Payment Entry",
				"docstatus": 1,
				"naming_series": settings.series_receipt_voucher,
				"payment_type": "Receive",
				"company": settings.company,
				"posting_date": frappe.utils.nowdate(),
				"party_type": "Customer",
				"party": frappe.db.get_value("Billing Profile", doc.team, "profile_id"),
				"paid_from": settings.advance_account,
				"paid_to": wallet_clearing_account(doc.currency),
				"paid_amount": amount,
				"received_amount": amount,
				"reference_no": f"{refund.name}-advance",
				"reference_date": frappe.utils.nowdate(),
				"company_address": settings.company_address,
				"company_gstin": gst.company_gstin(),
				"customer_address": frappe.db.get_value("Billing Profile", doc.team, "address_id"),
				"billing_address_gstin": tax.gstin,
				"gst_category": tax.gst_category,
				"place_of_supply": tax.place_of_supply,
				"taxes": gst.tax_rows(tax.template, paid_amount=amount) if gst_back else [],
				"remarks": f"Wallet credit returned from cancelled Central invoice {doc.name}",
			},
		).name
	# The returned credit in the wallet is backed by this advance from now on.
	frappe.db.set_value(
		"Credit Ledger Entry",
		{"reference_type": "Invoice", "reference_name": doc.name, "paid_in": 1, "entry_type": "Credit"},
		"advance_id",
		name,
	)
	return name


# --- helpers -------------------------------------------------------------------------


def _book_refund(doc, destination: str, amount, reason: str, **values) -> None:
	frappe.get_doc(
		{
			"doctype": "Refund",
			"invoice": doc.name,
			"team": doc.team,
			"amount": frappe.utils.flt(amount, 2),
			"currency": doc.currency,
			"destination": destination,
			"reason": reason,
			"status": _UNDER_WAY,
			"created_at": frappe.utils.now_datetime(),
			**values,
		}
	).insert(ignore_permissions=True)


def _reason(invoice: str) -> str:
	return (
		frappe.db.get_value("Refund", {"invoice": invoice}, "reason", order_by="creation asc") or "cancelled"
	)


def _refunds(invoice: str) -> list:
	return frappe.get_all(
		"Refund",
		filters={"invoice": invoice},
		fields=[
			"name",
			"destination",
			"amount",
			"status",
			"payment_attempt",
			"gateway_refund_id",
			"payment_record_id",
			"advance_id",
		],
		order_by="creation asc",
	)


def _captured_attempts(invoice: str) -> list:
	return frappe.get_all(
		"Payment Attempt",
		filters={"invoice": invoice, "status": "Captured"},
		fields=["name", "amount", "gateway", "gateway_transaction_id"],
	)


def _check_credit_note_deadline(doc) -> None:
	"""GST allows a credit note only until 30 November after the invoice's financial year."""
	if not frappe.utils.flt(doc.output_tax_amount):
		return
	issued = frappe.utils.getdate(doc.paid_at or doc.period_end)
	year_end = issued.year + 1 if issued.month > 3 else issued.year  # India's year ends 31 March
	deadline = frappe.utils.getdate(f"{year_end}-{CREDIT_NOTE_DEADLINE[0]:02d}-{CREDIT_NOTE_DEADLINE[1]:02d}")
	if frappe.utils.getdate() > deadline:
		frappe.throw(
			_("A credit note for this invoice was due by {0}, so it can no longer be cancelled.").format(
				frappe.utils.formatdate(deadline)
			),
			frappe.ValidationError,
		)


def _gateway_row(settings, gateway: str, currency: str):
	for row in settings.gateways:
		if row.gateway == gateway and row.currency == currency:
			return row
	raise RuntimeError(f"Billing Settings has no {gateway} {currency} row under Gateway Accounts")


def _adapter(gateway: str):
	from central.billing.gateways.registry import get_adapter

	return get_adapter(frappe.get_doc("Payment Gateway", gateway))


def _enqueue(invoice: str) -> None:
	frappe.enqueue(
		"central.billing.payments.corrections.run_cancellation",
		queue="short",
		job_id=f"cancellation::{invoice}::{frappe.generate_hash(length=6)}",
		enqueue_after_commit=True,
		invoice=invoice,
	)
