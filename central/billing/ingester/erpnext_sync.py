# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""ERPNext Sales Invoice sync — async, one-way, non-blocking (issue #17).

After a billable invoice is Paid, a background job pushes a Sales Invoice to
ERPNext (the statutory accounting SOR). Cloud Billing stays the SOR for the
customer-facing balance, so this sync is **strictly outbound** and **failure
isolated**: an ERPNext outage never blocks or rolls back the customer invoice —
it stays Paid, the failure is recorded, and the sync is retried with
exponential backoff (3 attempts) before ops is alerted.

Corrections (refund credit notes, #15) flow *down* the same outbound channel;
nothing is ever read back from ERPNext into billing.
"""

import frappe

from central.billing.ingester import connection, gst
from central.billing.ingester.settings import accounting_settings, invoice_series, receivable_account

MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 60  # 60s, 120s, 240s


def enqueue_invoice_sync(invoice: str):
	"""Post-payment hook: queue the ERPNext sync after the transaction commits."""
	frappe.enqueue(
		"central.billing.ingester.erpnext_sync.sync_invoice",
		invoice=invoice,
		enqueue_after_commit=True,
		queue="long",
	)


def sync_invoice(invoice: str) -> dict:
	"""Issue the ERPNext Sales Invoice for a Paid invoice, and record its card payment.

	Never raises into the caller and never touches the customer invoice's status.
	Each step is looked up before it is made, so a retry finishes the job instead
	of repeating it.
	"""
	if not connection.enabled():
		return {"skipped": "sync_off"}
	inv = frappe.get_doc("Invoice", invoice)
	if inv.invoice_type != "Billable":
		return {"skipped": "not_billable"}  # cost_report is not a statutory sale
	if inv.status != "Paid":
		return {"skipped": "not_paid"}
	if inv.erpnext_invoice and (inv.payment_record_id or not _card_attempt(inv)):
		return {"skipped": "already_synced"}

	attempt = (inv.erpnext_sync_attempts or 0) + 1
	try:
		customer = _customer_for(inv.team)
		if not inv.erpnext_invoice:
			inv.erpnext_invoice = _issue(inv, customer)
			frappe.db.set_value("Invoice", invoice, "erpnext_invoice", inv.erpnext_invoice)
		payment = _record_card_payment(inv, customer)
	except Exception as e:
		return _handle_failure(invoice, attempt, _error_text(e))

	frappe.db.set_value(
		"Invoice",
		invoice,
		{
			"payment_record_id": payment,
			"erpnext_sync_status": "Synced",
			"erpnext_sync_attempts": attempt,
			"erpnext_sync_error": None,
			"erpnext_next_retry_at": None,
		},
	)
	return {"synced": inv.erpnext_invoice, "payment": payment, "attempt": attempt}


def _handle_failure(invoice: str, attempt: int, error: str) -> dict:
	"""Record a failed attempt; schedule a backoff retry or alert ops. The
	customer invoice is never rolled back — it stays Paid."""
	values = {"erpnext_sync_attempts": attempt, "erpnext_sync_error": error[:1000]}
	if attempt >= MAX_ATTEMPTS:
		values["erpnext_sync_status"] = "Failed"
		values["erpnext_next_retry_at"] = None
		frappe.db.set_value("Invoice", invoice, values)
		_alert_ops(invoice, error)
		return {"failed": error, "attempts": attempt}

	backoff = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
	values["erpnext_sync_status"] = "Pending"
	values["erpnext_next_retry_at"] = frappe.utils.add_to_date(frappe.utils.now_datetime(), seconds=backoff)
	frappe.db.set_value("Invoice", invoice, values)
	return {"retry_scheduled": True, "attempt": attempt, "backoff_seconds": backoff}


def retry_failed_syncs(now=None) -> list:
	"""Scheduler: re-run syncs whose backoff window has elapsed."""
	now = now or frappe.utils.now_datetime()
	due = frappe.get_all(
		"Invoice",
		filters=[
			["erpnext_sync_status", "=", "Pending"],
			["erpnext_next_retry_at", "is", "set"],
			["erpnext_next_retry_at", "<=", now],
		],
		pluck="name",
	)
	return [sync_invoice(name) for name in due]


# --- ERPNext transport ------------------------------------------------------


def _customer_for(team: str) -> str:
	"""The team's customer in ERPNext. Missing one queues its sync and fails this try."""
	from central.billing.ingester.customer import ensure_customer

	customer = ensure_customer(team)
	if not customer:
		raise RuntimeError(f"team {team} has no customer in ERPNext yet; its sync is queued")
	return customer


def _issue(inv, customer: str) -> str:
	"""The submitted Sales Invoice for this invoice: found if it exists, else created."""
	existing = connection.find(
		"Sales Invoice", [["remarks", "like", f"%{_marker(inv)}%"], ["docstatus", "=", 1]], ["name"]
	)
	if existing:
		return existing[0].name
	return connection.post("api/resource/Sales Invoice", _build_sales_invoice(inv, customer)).name


def _build_sales_invoice(inv, customer: str) -> dict:
	"""Map a Central invoice to a submitted ERPNext Sales Invoice."""
	settings = accounting_settings()
	tax = gst.treatment(inv.team)
	# The GST on our invoice decides the rows. A lapsed GSTIN was billed as unregistered.
	template = tax.template if frappe.utils.flt(inv.output_tax_amount) else None
	advances, unbacked = _advances(inv)
	remarks = _marker(inv)
	if unbacked:
		remarks += f". Wallet credit not backed by an advance: {unbacked}"
	return {
		"doctype": "Sales Invoice",
		"docstatus": 1,
		"naming_series": invoice_series(inv.team),
		"company": settings.company,
		"customer": customer,
		"currency": inv.currency,
		"debit_to": receivable_account(inv.currency),
		"due_date": frappe.utils.nowdate(),
		"company_address": settings.company_address,
		"company_gstin": gst.company_gstin(),
		"customer_address": frappe.db.get_value("Billing Profile", inv.team, "address_id"),
		"billing_address_gstin": inv.customer_gstin or "",
		"gst_category": _gst_category(inv, tax),
		"place_of_supply": tax.place_of_supply,
		"taxes_and_charges": template,
		"taxes": gst.tax_rows(template),
		"items": [_item(li, settings) for li in inv.items],
		"advances": advances,
		"allocate_advances_automatically": 0,
		"disable_rounded_total": 1,
		"ignore_pricing_rule": 1,
		"remarks": remarks,
	}


def _item(line, settings) -> dict:
	label = " · ".join(x for x in (line.plan or line.resource_type, line.subscription_resource) if x)
	period = f"{line.period_from or ''} to {line.period_to or ''}" if line.period_from else ""
	return {
		"item_code": settings.service_item,
		"description": " · ".join(x for x in (label or "Usage", period) if x),
		"qty": 1,
		"rate": frappe.utils.flt(line.amount),
		"income_account": settings.income_account,
		"cost_center": settings.cost_center,
	}


def _gst_category(inv, tax) -> str:
	if tax.gst_category == "Overseas" or inv.customer_gstin:
		return tax.gst_category
	return "Unregistered"


def _advances(inv) -> tuple[list[dict], float]:
	"""The advances this invoice's paid top-up credit came from, oldest first.

	Returns the rows and any wallet credit no advance covers (promotional credit).
	"""
	needed = frappe.utils.flt(inv.advance_applied)
	unbacked = frappe.utils.flt(frappe.utils.flt(inv.credit_applied) - needed, 2)
	if needed <= 0:
		return [], unbacked
	pending = frappe.get_all(
		"Credit Ledger Entry",
		filters=[
			["team", "=", inv.team],
			["gateway_payment_id", "is", "set"],
			["advance_id", "is", "not set"],
		],
		limit=1,
	)
	returning = frappe.get_all(
		"Refund",
		filters={
			"team": inv.team,
			"destination": "Wallet",
			"status": "Completed",
			"advance_id": ["is", "not set"],
		},
		pluck="invoice",
	)
	if returning and frappe.get_all(
		"Invoice", filters={"name": ["in", returning], "erpnext_invoice": ["is", "set"]}, limit=1
	):
		pending = True  # credit given back from a cancelled invoice is not an advance yet
	if pending:
		raise RuntimeError(f"a wallet credit of team {inv.team} has no advance yet; its sync is queued")

	rows = []
	for advance_id in frappe.get_all(
		"Credit Ledger Entry",
		filters=[["team", "=", inv.team], ["advance_id", "is", "set"], ["currency", "=", inv.currency]],
		pluck="advance_id",
		order_by="creation asc",
	):
		unallocated = frappe.utils.flt(
			(connection.fetch("Payment Entry", advance_id) or {}).get("unallocated_amount")
		)
		# The advance is held without its GST, the same as the credit. Its GST comes
		# back to settle this invoice's GST as the credit is used.
		take = min(unallocated, needed)
		if take <= 0:
			continue
		rows.append(
			{
				"reference_type": "Payment Entry",
				"reference_name": advance_id,
				"advance_amount": unallocated,
				"allocated_amount": frappe.utils.flt(take, 2),
			}
		)
		needed = frappe.utils.flt(needed - take, 2)
		if needed <= 0:
			break
	return rows, unbacked


def _card_attempt(inv):
	"""The captured card or UPI payment that settled this invoice, if one did."""
	if frappe.utils.flt(inv.amount_paid) <= 0:
		return None
	name = frappe.db.get_value(
		"Payment Attempt", {"invoice": inv.name, "status": "Captured"}, "name", order_by="creation desc"
	)
	return frappe.get_doc("Payment Attempt", name) if name else None


def _record_card_payment(inv, customer: str) -> str | None:
	"""A Payment Entry against the Sales Invoice for what the card paid. Found if it exists."""
	attempt = _card_attempt(inv)
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
	owed = frappe.utils.flt(sales_invoice.outstanding_amount)
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
		"remarks": f"{attempt.gateway} payment {attempt.gateway_transaction_id} for {_marker(inv)}",
	}
	return connection.post("api/resource/Payment Entry", payload).name


def _gateway_row(settings, gateway: str, currency: str):
	for row in settings.gateways:
		if row.gateway == gateway and row.currency == currency:
			return row
	raise RuntimeError(f"Billing Settings has no {gateway} {currency} row under Gateway Accounts")


def _marker(inv) -> str:
	return f"Central invoice {inv.name}"


def _error_text(error: Exception) -> str:
	response = getattr(error, "response", None)
	if response is not None:
		try:
			body = response.json()
			messages = body.get("_server_messages") or body.get("exception") or body
			return str(messages)[:1000]
		except ValueError:
			return response.text[:1000]
	return str(error)[:1000]


def sales_invoice_pdf(sales_invoice: str) -> bytes:
	"""The statutory invoice as a PDF, rendered by ERPNext with the configured print format."""
	settings = accounting_settings()
	return connection.print_pdf(
		"Sales Invoice", sales_invoice, settings.invoice_print_format, settings.invoice_letter_head
	)


def _alert_ops(invoice: str, error: str):
	"""After the retry budget is spent, surface the failure to ops (not the
	customer — their invoice is Paid and unaffected)."""
	frappe.log_error(
		title=f"ERPNext sync failed: {invoice}",
		message=f"Sales Invoice sync for {invoice} failed after {MAX_ATTEMPTS} attempts: {error}",
	)
	frappe.get_doc("Invoice", invoice).add_comment(
		"Info", f"ERPNext sync failed after {MAX_ATTEMPTS} attempts — queued for ops follow-up."
	)
