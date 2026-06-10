# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Charge an open invoice and settle it on the webhook (issue #10).

The money loop: an `Open` invoice with an amount due gets a `Payment Attempt`
(idempotency_key = the attempt's name), is charged through the adapter, and is
marked `Paid` **only** when the gateway webhook confirms it — never on the
synchronous charge response. Each retry is a new attempt; concurrent charges of
one invoice produce at most one in-flight attempt, so only one reaches
`captured`.
"""

import frappe

from central.billing.gateways.base import GatewayTimeout

# An attempt occupying the invoice — a second charge must not start beside it.
_IN_FLIGHT = ("initiated", "authorised", "captured")

# Gateway event types the Payment Attempt listens to. An attempt's status is
# advanced ONLY by the respective callback for its transaction:
#   initiated -> authorised -> captured / failed
# `authorised` (funds held, not yet captured) moves no money and leaves the
# invoice Open; `captured` is the only event that settles it to Paid.
_AUTHORISED_EVENTS = {
	"payment_intent.amount_capturable_updated",  # Stripe: requires_capture
	"payment.authorized",  # Razorpay
	"charge.authorized",
}
_SUCCESS_EVENTS = {"payment_intent.succeeded", "charge.succeeded", "payment.captured"}
_FAILURE_EVENTS = {"payment_intent.payment_failed", "charge.failed", "payment.failed"}

# Logs (Payment Attempt + Webhook Event) are kept on a rolling window and pruned
# daily; site-config `payment_log_retention_days` overrides the default.
LOG_RETENTION_DEFAULT_DAYS = 90  # ~3 months
_TERMINAL_ATTEMPT = ("captured", "failed", "refunded")
_UNSETTLED_INVOICE = ("Open", "Overdue")


def _adapter_for(gateway: str):
	from central.billing.gateways.registry import get_adapter

	return get_adapter(frappe.get_doc("Payment Gateway", gateway))


@frappe.whitelist()
def pay_invoice(invoice: str, payment_method: str | None = None, gateway: str | None = None) -> dict:
	"""Charge an Open invoice. Creates at most one in-flight Payment Attempt.

	The invoice row is locked FOR UPDATE for the whole attempt, so concurrent
	callers serialise: the first creates and charges an attempt; the rest see it
	in flight and return without starting a second charge. The invoice is never
	marked Paid here — that waits for the webhook.
	"""
	invoice_tbl = frappe.qb.DocType("Invoice")
	frappe.qb.from_(invoice_tbl).select(invoice_tbl.name).where(
		invoice_tbl.name == invoice
	).for_update().run()
	inv = frappe.get_doc("Invoice", invoice)

	if inv.status != "Open":
		return {"charged": False, "reason": "not_open"}
	if frappe.utils.flt(inv.expected_collection) <= 0:
		return {"charged": False, "reason": "nothing_due"}

	in_flight = frappe.get_all(
		"Payment Attempt", {"invoice": invoice, "status": ["in", _IN_FLIGHT]}, pluck="name"
	)
	if in_flight:
		return {"charged": False, "reason": "attempt_in_flight", "attempt": in_flight[0]}

	method_name, gateway_name = _resolve_method(inv, payment_method, gateway)
	method = frappe.get_doc("Payment Method", method_name)

	attempt = frappe.get_doc(
		{
			"doctype": "Payment Attempt",
			"invoice": invoice,
			"team": inv.team,
			"gateway": gateway_name,
			"payment_method": method_name,
			"amount": inv.expected_collection,
			"currency": inv.currency,
			"status": "initiated",
			"initiated_at": frappe.utils.now_datetime(),
			"retry_number": frappe.db.count("Payment Attempt", {"invoice": invoice}),
		}
	).insert(ignore_permissions=True)

	charge_input = frappe._dict(
		amount=frappe.utils.flt(inv.expected_collection),
		currency=inv.currency,
		customer_id=method.gateway_customer_id,
		name=invoice,
	)
	try:
		result = _adapter_for(gateway_name).charge(charge_input, method, attempt.idempotency_key)
	except GatewayTimeout as e:
		# Transient: leave the attempt initiated so a retry reuses the same key.
		attempt.failure_reason = str(e)[:140]
		attempt.save(ignore_permissions=True)
		return {"charged": False, "reason": "timeout", "attempt": attempt.name}

	attempt.gateway_transaction_id = result.gateway_transaction_id
	if result.success:
		attempt.status = "captured"  # gateway captured; invoice Paid waits on webhook
	else:
		attempt.status = "failed"
		attempt.failure_code = result.failure_code
		attempt.failure_reason = result.failure_reason
		attempt.completed_at = frappe.utils.now_datetime()
	attempt.save(ignore_permissions=True)

	return {"charged": result.success, "attempt": attempt.name, "status": attempt.status}


def _resolve_method(inv, payment_method, gateway):
	"""Method + gateway for the charge: explicit args, then subscription default,
	then currency-based gateway lookup via the resolver."""
	if payment_method and gateway:
		return payment_method, gateway
	sub = frappe.get_doc("Subscription", inv.subscription) if inv.subscription else None
	method_name = payment_method or (sub and sub.default_payment_method)
	gateway_name = gateway or (sub and sub.gateway)

	if not gateway_name and inv.currency:
		from central.billing.gateways.registry import GatewayNotFound, resolve_gateway_for_currency

		try:
			gateway_name = resolve_gateway_for_currency(inv.currency)
		except GatewayNotFound:
			pass

	if not method_name or not gateway_name:
		frappe.throw(f"No payment method/gateway resolved for {inv.name}", frappe.ValidationError)
	return method_name, gateway_name


# --- webhook settlement -----------------------------------------------------


def apply_webhook(event_name: str) -> dict:
	"""Drive Open -> Paid from a stored, signature-verified Webhook Event.

	Finds the Payment Attempt by the gateway transaction id carried in the event
	and, on a success event, marks the invoice Paid + records amount_paid. This
	is the ONLY path that sets Paid.
	"""
	event = frappe.get_doc("Webhook Event", event_name)
	adapter_key = frappe.db.get_value("Payment Gateway", event.gateway, "adapter_key")
	payload = frappe.parse_json(event.raw_payload) if event.raw_payload else {}

	txn_id = _extract_transaction_id(adapter_key, payload)
	is_authorised = event.event_type in _AUTHORISED_EVENTS
	is_success = event.event_type in _SUCCESS_EVENTS
	is_failure = event.event_type in _FAILURE_EVENTS

	if not txn_id or not (is_authorised or is_success or is_failure):
		_mark_event(event, "ignored")
		return {"handled": False, "reason": "not_a_charge_event"}

	attempt_name = frappe.db.get_value("Payment Attempt", {"gateway_transaction_id": txn_id}, "name")
	if not attempt_name:
		_mark_event(event, "ignored")
		return {"handled": False, "reason": "no_matching_attempt"}

	attempt = frappe.get_doc("Payment Attempt", attempt_name)
	if is_authorised:
		# Funds held, capture pending. Advance only from initiated — never walk a
		# terminal attempt backwards if the capture/fail webhook arrived first.
		if attempt.status == "initiated":
			attempt.status = "authorised"
			attempt.save(ignore_permissions=True)
		_mark_event(event, "processed")
		return {"handled": True, "result": "authorised", "attempt": attempt_name}

	if is_failure:
		fell_back = None
		# A failure matters only until the invoice is settled — never undo a Paid
		# invoice (a sync `captured` attempt isn't final: Paid lands on the success
		# webhook). Gate on invoice status, not attempt status, and act once.
		inv_status = frappe.db.get_value("Invoice", attempt.invoice, "status")
		if inv_status != "Paid" and attempt.status not in ("failed", "refunded"):
			attempt.status = "failed"
			attempt.completed_at = frappe.utils.now_datetime()
			attempt.save(ignore_permissions=True)
			from central.billing.platform import notifications

			notifications.notify(
				attempt.team, "payment_failure",
				context={"invoice": attempt.invoice, "reason": attempt.failure_reason or "declined"},
				reference_doctype="Invoice", reference_name=attempt.invoice,
			)
			# Async decline: rotate to the next untried method (#28). No-op once
			# every method has been exhausted.
			if inv_status in ("Open", "Overdue"):
				from central.billing.payments import collection

				fell_back = collection.collect_invoice(attempt.invoice)
		_mark_event(event, "processed")
		return {"handled": True, "result": "failed", "attempt": attempt_name, "fell_back": fell_back}

	settled = _settle_invoice(attempt)
	attempt.status = "captured"
	attempt.completed_at = frappe.utils.now_datetime()
	attempt.resolved_by = "webhook"
	attempt.save(ignore_permissions=True)
	_mark_event(event, "processed")
	return {"handled": True, "result": "paid", "invoice": attempt.invoice, "settled": settled}


def _settle_invoice(attempt) -> bool:
	"""Mark the attempt's invoice Paid (idempotent, under a row lock)."""
	invoice_tbl = frappe.qb.DocType("Invoice")
	frappe.qb.from_(invoice_tbl).select(invoice_tbl.name).where(
		invoice_tbl.name == attempt.invoice
	).for_update().run()
	inv = frappe.get_doc("Invoice", attempt.invoice)
	if inv.status == "Paid":
		return False  # a duplicate webhook — already settled
	inv.amount_paid = frappe.utils.flt(attempt.amount)
	inv.status = "Paid"
	inv.save(ignore_permissions=True)

	from central.billing.platform import notifications

	notifications.notify(
		inv.team, "payment_success",
		message=f"Invoice {inv.name} paid ({inv.amount_paid} {inv.currency or ''}).",
		reference_doctype="Invoice", reference_name=inv.name,
	)

	# Async, one-way, non-blocking push to the statutory SOR (#17).
	from central.billing.revenue.erpnext_sync import enqueue_invoice_sync

	enqueue_invoice_sync(inv.name)
	return True


# --- log retention ----------------------------------------------------------


def cleanup_payment_logs(now=None) -> dict:
	"""Daily: prune Payment Attempt + Webhook Event logs past the retention window.

	These are high-volume append-only logs (one row per charge / per inbound
	callback). They are kept on a rolling window — site-config
	`payment_log_retention_days`, default 90 (~3 months) — and older rows are
	dropped. Statutory amounts live on the Invoice / ERPNext Sales Invoice (the
	SOR), so pruning the gateway log loses no money trail.

	A *live* record is never pruned: a non-terminal attempt (initiated/
	authorised), an attempt on an unsettled invoice (Open/Overdue), or one
	referenced by a Refund is kept regardless of age.
	"""
	days = int(frappe.conf.get("payment_log_retention_days") or LOG_RETENTION_DEFAULT_DAYS)
	cutoff = frappe.utils.add_to_date(now or frappe.utils.now_datetime(), days=-days)

	attempts = _prune_payment_attempts(cutoff)
	events = _prune_webhook_events(cutoff)
	return {"cutoff": str(cutoff), "payment_attempts": attempts, "webhook_events": events}


def _prune_payment_attempts(cutoff) -> int:
	"""Delete terminal attempts older than cutoff, keeping any the audit chain or
	an open invoice still needs."""
	# Attempts referenced by a Refund anchor the refund audit chain — never drop.
	keep = set(frappe.get_all("Refund", pluck="payment_attempt") or [])
	candidates = frappe.get_all(
		"Payment Attempt",
		filters={"status": ["in", _TERMINAL_ATTEMPT], "creation": ["<", cutoff]},
		fields=["name", "invoice"],
	)
	deleted = 0
	for a in candidates:
		if a.name in keep:
			continue
		if frappe.db.get_value("Invoice", a.invoice, "status") in _UNSETTLED_INVOICE:
			continue
		frappe.delete_doc("Payment Attempt", a.name, ignore_permissions=True, force=True, delete_permanently=True)
		deleted += 1
	return deleted


def _prune_webhook_events(cutoff) -> int:
	"""Delete processed/ignored Webhook Event rows older than cutoff. Keep any not
	yet handled (received/failed) so a stuck event stays visible for triage."""
	stale = frappe.get_all(
		"Webhook Event",
		filters={"status": ["in", ("processed", "ignored")], "creation": ["<", cutoff]},
		pluck="name",
	)
	for name in stale:
		frappe.delete_doc("Webhook Event", name, ignore_permissions=True, force=True, delete_permanently=True)
	return len(stale)


def _extract_transaction_id(adapter_key: str, payload: dict):
	"""Pull the gateway transaction id out of a parsed webhook body."""
	if adapter_key == "stripe":
		return ((payload.get("data") or {}).get("object") or {}).get("id")
	if adapter_key == "razorpay":
		payment = (((payload.get("payload") or {}).get("payment") or {}).get("entity")) or {}
		return payment.get("id")
	return None


def _mark_event(event, status: str):
	event.status = status
	event.processed_at = frappe.utils.now_datetime()
	event.save(ignore_permissions=True)


def _notify(invoice, message: str):
	"""Log a billing notification (the #20 suite is the real sender)."""
	invoice.add_comment("Info", message)
