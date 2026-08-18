# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Charge an open invoice and settle it on the webhook (issue #10).

The money loop: an `Open` invoice with an amount due gets a `Payment Attempt`, is
charged through the adapter, and is marked `Paid` **only** when the gateway webhook
confirms it — never on the synchronous charge response. Each retry is a new attempt;
concurrent charges of one invoice produce at most one in-flight attempt, so only one
reaches `captured`.

The attempt is saved *and committed* before the gateway is called (ADR 0017). A
crash mid-charge therefore leaves the attempt sitting at `Initiated` — a charge
whose result we don't know yet, which reconciliation can go and ask the gateway
about. It can never leave a charge with no record of it at all.
"""

import frappe
from frappe import _

from central.billing import settings
from central.billing.doctype.payment_attempt.payment_attempt import idempotency_key
from central.billing.gateways.base import GatewayTimeout
from central.billing.states import transition

# An attempt occupying the invoice — a second charge must not start beside it.
_IN_FLIGHT = ("Initiated", "Authorised", "Captured")

# The unique idempotency key rejected the insert: this charge is already claimed.
_ALREADY_CLAIMED = (frappe.UniqueValidationError, frappe.DuplicateEntryError)

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

_TERMINAL_ATTEMPT = ("Captured", "Failed", "Refunded")
_UNSETTLED_INVOICE = ("Open", "Overdue")


def _adapter_for(gateway: str):
	from central.billing.gateways.registry import get_adapter

	return get_adapter(frappe.get_doc("Payment Gateway", gateway))


def pay_invoice(invoice: str, payment_method: str | None = None, gateway: str | None = None) -> dict:
	"""Charge an unsettled (Open or Overdue) invoice. Creates at most one in-flight
	Payment Attempt.

	Two steps, with the gateway call sitting between them:

	  1. claim  — lock the invoice, check nothing is already in flight, save the
	              Payment Attempt and commit it. We now have a durable record that
	              we are about to charge this card.
	  2. charge — call the gateway with the attempt's key, then write down what came
	              back.

	Splitting it this way is what makes a crash survivable: the money can only move
	after step 1 is on disk, so there is always a record to reconcile against. The
	invoice is never marked Paid here — that waits for the webhook.
	"""
	claim = _claim_attempt(invoice, payment_method, gateway)
	if not claim.get("claimed"):
		return claim
	return _charge_claimed_attempt(claim["attempt"])


def _claim_attempt(invoice: str, payment_method: str | None, gateway: str | None) -> dict:
	"""Step 1: write down that we are about to charge, and commit it.

	The invoice row is locked FOR UPDATE, so concurrent callers serialise: the first
	claims an attempt, the rest see it in flight and return. The unique idempotency
	key is the backstop for the case the lock can't cover — a worker that crashed
	after charging, leaving no row to see — where a duplicate key means someone else
	already owns this charge.
	"""
	invoice_tbl = frappe.qb.DocType("Invoice")
	frappe.qb.from_(invoice_tbl).select(invoice_tbl.name).where(
		invoice_tbl.name == invoice
	).for_update().run()
	inv = frappe.get_doc("Invoice", invoice)

	# An Overdue invoice is still collectable — retrying the card is exactly what a
	# customer clicking Pay (or dunning) does — so allow both unsettled states.
	if inv.status not in _UNSETTLED_INVOICE:
		return {"charged": False, "reason": "not_open"}
	if frappe.utils.flt(inv.expected_collection) <= 0:
		return {"charged": False, "reason": "nothing_due"}

	in_flight = frappe.get_all(
		"Payment Attempt", {"invoice": invoice, "status": ["in", _IN_FLIGHT]}, pluck="name"
	)
	if in_flight:
		return {"charged": False, "reason": "attempt_in_flight", "attempt": in_flight[0]}

	method_name, gateway_name = _resolve_method(inv, payment_method, gateway)
	adapter = _adapter_for(gateway_name)

	# A debit the gateway can't pull silently in this currency (INR above ₹15,000 —
	# an RBI off-session rule that binds Stripe India and Razorpay alike) is never
	# attempted: it would just fail. Instead raise Action Required so the customer
	# picks manual checkout / prepaid (ADR 0022, #106). An uncapped currency and
	# anything under the ceiling pass straight through.
	if not adapter.can_charge_silently(frappe.utils.flt(inv.expected_collection), inv.currency):
		from central.billing.payments import collection_mode

		collection_mode.trip(inv.team, "invoice_over_threshold")
		return {"charged": False, "reason": "action_required", "invoice": invoice}

	retry_number = frappe.db.count("Payment Attempt", {"invoice": invoice})
	save_point = "claim_payment_attempt"
	frappe.db.savepoint(save_point)
	try:
		attempt = frappe.get_doc(
			{
				"doctype": "Payment Attempt",
				"invoice": invoice,
				"team": inv.team,
				"gateway": gateway_name,
				"payment_method": method_name,
				"amount": inv.expected_collection,
				"currency": inv.currency,
				"status": "Initiated",
				"initiated_at": frappe.utils.now_datetime(),
				"retry_number": retry_number,
			}
		).insert(ignore_permissions=True)
	except _ALREADY_CLAIMED:
		# Someone else already claimed this exact charge (same invoice, same retry
		# number, so the same key). They own it; we don't start a second one. Undo
		# only the failed insert — whatever the caller did before this still stands.
		frappe.db.rollback(save_point=save_point)
		owner = frappe.db.get_value(
			"Payment Attempt", {"idempotency_key": idempotency_key(invoice, retry_number)}, "name"
		)
		return {"charged": False, "reason": "attempt_in_flight", "attempt": owner}

	# The record of intent must survive a crash during the charge, so it goes to disk
	# now, before any money moves. (Skipped under tests, where the row stays visible
	# inside the test transaction.)
	if not frappe.in_test:
		frappe.db.commit()
	return {"claimed": True, "attempt": attempt.name}


def _charge_claimed_attempt(attempt_name: str) -> dict:
	"""Step 2: call the gateway for a claimed attempt and record the outcome.

	Anything that goes wrong here — a timeout, an unmapped adapter error, the worker
	being killed — leaves the attempt at `Initiated`, which reconciliation reads as
	"we charged and don't know the result" and resolves against the gateway.
	"""
	attempt = frappe.get_doc("Payment Attempt", attempt_name)
	method = frappe.get_doc("Payment Method", attempt.payment_method)
	adapter = _adapter_for(attempt.gateway)

	charge_input = frappe._dict(
		amount=frappe.utils.flt(attempt.amount),
		currency=attempt.currency,
		customer_id=method.gateway_customer_id,
		name=attempt.invoice,
	)
	try:
		result = adapter.charge(charge_input, method, attempt.idempotency_key)
	except GatewayTimeout as e:
		# Transient: leave the attempt initiated so a retry reuses the same key.
		attempt.failure_reason = str(e)[:140]
		attempt.save(ignore_permissions=True)
		# We never reached the customer — a rate limit or a network fault is ours, not
		# theirs — so their retry ladder must not start ticking on it.
		from central.billing.revenue.dunning import defer_dunning

		defer_dunning(attempt.invoice, f"gateway unreachable: {str(e)[:80]}")
		_persist()
		return {"charged": False, "reason": "timeout", "attempt": attempt.name}

	attempt.gateway_transaction_id = result.gateway_transaction_id
	# The gateway is holding the charge on purpose — Stripe's India pre-debit window,
	# where the bank notifies the customer first and the money moves a day later. It
	# has neither succeeded nor failed, so the attempt stays in flight and nothing
	# retries or falls back against it (ADR 0023).
	if result.hold_until:
		attempt.gateway_hold_until = result.hold_until
		attempt.save(ignore_permissions=True)
		_persist()
		return {
			"charged": False,
			"attempt": attempt.name,
			"status": attempt.status,
			"reason": "gateway_hold",
			"hold_until": result.hold_until,
		}
	if result.success:
		# gateway captured; invoice Paid waits on the webhook
		transition(attempt, "Captured", actor="gateway", correlation=attempt.invoice)
	else:
		transition(
			attempt, "Failed", actor="gateway", correlation=attempt.invoice, reason=result.failure_reason
		)
		_stamp_failure(attempt, result.failure_code, result.decline_code, result.failure_reason, result.raw)
		attempt.completed_at = frappe.utils.now_datetime()
		_retire_method_if_mandate_failed(attempt, result.failure_code)
	attempt.save(ignore_permissions=True)
	_persist()

	return {
		"charged": result.success,
		"attempt": attempt.name,
		"status": attempt.status,
		"failure_code": result.failure_code,
	}


def resume_attempt(attempt: str) -> dict:
	"""Finish a claimed charge we never got an answer to (used by reconciliation).

	Re-sends the same request with the same key. If the gateway already took the
	money, it replays that first result and no second charge happens; if the request
	never reached it, it charges now — which is what the invoice was waiting for.
	Either way the attempt ends up terminal instead of stuck.
	"""
	att = frappe.get_doc("Payment Attempt", attempt)
	if att.status != "Initiated" or att.gateway_transaction_id or not att.payment_method:
		return {"charged": False, "reason": "not_resumable", "attempt": attempt}
	return _charge_claimed_attempt(attempt)


def _persist():
	"""Commit the gateway's answer — it must outlive whatever the caller does next.
	Skipped under tests, where writes stay inside the test transaction."""
	if not frappe.in_test:
		frappe.db.commit()


# --- on-session manual checkout (collection_mode = manual_checkout) ----------
# A customer-present payment of an open invoice. On-session carries NO ₹15,000
# silent-debit limit (that's an off-session rule), so any amount is payable
# (ADR 0005, #50). It reuses the Payment Attempt + capture-webhook settlement
# path, so the invoice is marked Paid only by the webhook — never on confirm.


def create_invoice_payment_order(invoice: str, gateway: str | None = None) -> dict:
	"""Open a gateway order for an Open invoice the customer pays on-session, and
	record an Initiated Payment Attempt to settle against. Returns the checkout
	handles; the invoice is not touched here."""
	invoice_tbl = frappe.qb.DocType("Invoice")
	frappe.qb.from_(invoice_tbl).select(invoice_tbl.name).where(
		invoice_tbl.name == invoice
	).for_update().run()
	inv = frappe.get_doc("Invoice", invoice)

	if inv.status not in ("Open", "Overdue"):
		return {"created": False, "reason": "not_open"}
	if frappe.utils.flt(inv.expected_collection) <= 0:
		return {"created": False, "reason": "nothing_due"}
	in_flight = frappe.get_all(
		"Payment Attempt", {"invoice": invoice, "status": ["in", _IN_FLIGHT]}, pluck="name"
	)
	if in_flight:
		return {"created": False, "reason": "attempt_in_flight", "attempt": in_flight[0]}

	gateway_name = gateway or _gateway_for_invoice(inv)
	gw_doc = frappe.get_doc("Payment Gateway", gateway_name)
	adapter = _adapter_for(gateway_name)
	amount = frappe.utils.flt(inv.expected_collection)
	receipt = f"inv-{invoice}-{frappe.generate_hash(length=8)}"
	handles = adapter.create_order(
		amount, inv.currency, receipt, notes={"invoice": invoice, "purpose": "invoice_payment"}
	)
	attempt = frappe.get_doc(
		{
			"doctype": "Payment Attempt",
			"invoice": invoice,
			"team": inv.team,
			"gateway": gateway_name,
			"amount": amount,
			"currency": inv.currency,
			"status": "Initiated",
			"initiated_at": frappe.utils.now_datetime(),
			"retry_number": frappe.db.count("Payment Attempt", {"invoice": invoice}),
		}
	).insert(ignore_permissions=True)
	return {
		"created": True,
		"attempt": attempt.name,
		"gateway": gateway_name,
		"adapter_key": gw_doc.adapter_key,
		"amount": amount,
		"currency": inv.currency,
		"receipt": receipt,
		**handles,
	}


def confirm_invoice_payment(
	attempt: str,
	razorpay_order_id: str | None = None,
	razorpay_payment_id: str | None = None,
	razorpay_signature: str | None = None,
) -> dict:
	"""Verify the on-session checkout callback and stamp the attempt with the gateway
	payment id. The invoice flips to Paid on the capture webhook (webhook-truth),
	not here — so a faked callback can never mark an invoice paid on its own."""
	att = frappe.get_doc("Payment Attempt", attempt)
	ok = _adapter_for(att.gateway).verify_payment_signature(
		{
			"razorpay_order_id": razorpay_order_id,
			"razorpay_payment_id": razorpay_payment_id,
			"razorpay_signature": razorpay_signature,
		}
	)
	if not ok:
		frappe.throw(_("Payment confirmation failed."), frappe.ValidationError)
	att.gateway_transaction_id = razorpay_payment_id
	# gateway captured; invoice Paid waits on the webhook
	transition(att, "Captured", actor="gateway", correlation=att.invoice)
	att.save(ignore_permissions=True)
	return {"confirmed": True, "attempt": att.name, "status": att.status}


def _gateway_for_invoice(inv) -> str:
	"""The gateway that settles this invoice's currency (on-session top-up rail)."""
	from central.billing.gateways.registry import resolve_gateway_for_currency

	return resolve_gateway_for_currency(inv.currency)


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
		frappe.throw(_("No payment method/gateway resolved for {0}").format(inv.name), frappe.ValidationError)
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
		_mark_event(event, "Ignored")
		return {"handled": False, "reason": "not_a_charge_event"}

	# Wallet top-ups carry no Payment Attempt — they're settled by crediting the
	# wallet directly. The browser's confirm callback normally does it; this is the
	# server-authoritative backstop for when that callback never lands. Idempotent
	# on the gateway payment id, so it never double-credits beside confirm_topup.
	topup = _extract_topup(adapter_key, payload)
	if topup:
		if not is_success:
			# Authorised/failed top-up callback: nothing to credit yet (or ever).
			_mark_event(event, "Ignored")
			return {"handled": False, "reason": "topup_not_captured"}
		return _credit_topup(event, topup)

	# Hosted-checkout invoice payments (create_invoice_checkout) also carry no Payment
	# Attempt — they settle the invoice from the `invoice_payment` notes, same as top-ups.
	inv_pay = _extract_invoice_payment(adapter_key, payload)
	if inv_pay:
		if not is_success:
			_mark_event(event, "Ignored")
			return {"handled": False, "reason": "invoice_payment_not_captured"}
		return _settle_invoice_payment(event, inv_pay)

	attempt_name = frappe.db.get_value("Payment Attempt", {"gateway_transaction_id": txn_id}, "name")
	if not attempt_name:
		_mark_event(event, "Ignored")
		return {"handled": False, "reason": "no_matching_attempt"}

	attempt = frappe.get_doc("Payment Attempt", attempt_name)
	if is_authorised:
		# Funds held, capture pending. Advance only from initiated — never walk a
		# terminal attempt backwards if the capture/fail webhook arrived first.
		if attempt.status == "Initiated":
			transition(attempt, "Authorised", actor="webhook", correlation=attempt.invoice)
			attempt.save(ignore_permissions=True)
		_mark_event(event, "Processed")
		return {"handled": True, "result": "Authorised", "attempt": attempt_name}

	if is_failure:
		fell_back = None
		# A failure matters only until the invoice is settled — never undo a Paid
		# invoice (a sync `captured` attempt isn't final: Paid lands on the success
		# webhook). Gate on invoice status, not attempt status, and act once.
		inv_status = frappe.db.get_value("Invoice", attempt.invoice, "status")
		if inv_status != "Paid" and attempt.status not in ("Failed", "Refunded"):
			transition(attempt, "Failed", actor="webhook", correlation=attempt.invoice)
			# Off-session declines surface their real reason here, not on the sync
			# charge response — pull it off the event so the attempt records why.
			detail = _extract_failure(adapter_key, payload)
			if detail:
				_stamp_failure(
					attempt,
					detail.get("failure_code"),
					detail.get("decline_code"),
					detail.get("failure_reason"),
					detail.get("raw"),
				)
			attempt.completed_at = frappe.utils.now_datetime()
			attempt.save(ignore_permissions=True)
			from central.billing.platform import notifications

			notifications.notify(
				attempt.team,
				"Payment Failure",
				context={"invoice": attempt.invoice, "reason": attempt.failure_reason or "declined"},
				reference_doctype="Invoice",
				reference_name=attempt.invoice,
			)
			# Async decline: rotate to the next untried method (#28). No-op once
			# every method has been exhausted.
			if inv_status in ("Open", "Overdue"):
				from central.billing.payments import collection

				fell_back = collection.collect_invoice(attempt.invoice)
		_mark_event(event, "Processed")
		return {"handled": True, "result": "Failed", "attempt": attempt_name, "fell_back": fell_back}

	settled = _settle_invoice(attempt)
	transition(attempt, "Captured", actor="webhook", correlation=attempt.invoice)
	attempt.completed_at = frappe.utils.now_datetime()
	attempt.resolved_by = "Webhook"
	attempt.save(ignore_permissions=True)
	_mark_event(event, "Processed")
	return {"handled": True, "result": "paid", "invoice": attempt.invoice, "settled": settled}


def _settle_invoice(attempt) -> bool:
	"""Mark the attempt's invoice Paid (idempotent, under a row lock)."""
	return _mark_invoice_paid(attempt.invoice, attempt.amount)


def _mark_invoice_paid(invoice: str, amount) -> bool:
	"""Mark an invoice Paid (idempotent, under a row lock). Shared by the Payment
	Attempt capture path and the hosted-checkout invoice-payment path."""
	invoice_tbl = frappe.qb.DocType("Invoice")
	frappe.qb.from_(invoice_tbl).select(invoice_tbl.name).where(
		invoice_tbl.name == invoice
	).for_update().run()
	inv = frappe.get_doc("Invoice", invoice)
	if inv.status == "Paid":
		return False  # a duplicate webhook — already settled
	inv.amount_paid = frappe.utils.flt(amount)
	inv.paid_at = frappe.utils.now_datetime()
	transition(
		inv,
		"Paid",
		reason="gateway capture settled",
		actor="webhook",
		correlation=inv.name,
		amount=inv.amount_paid,
	)
	inv.save(ignore_permissions=True)

	from central.billing.platform import notifications

	notifications.notify(
		inv.team,
		"Payment Success",
		message=f"Invoice {inv.name} paid ({inv.amount_paid} {inv.currency or ''}).",
		reference_doctype="Invoice",
		reference_name=inv.name,
	)

	# Async, one-way, non-blocking push to the statutory SOR (#17).
	from central.billing.revenue.erpnext_sync import enqueue_invoice_sync

	enqueue_invoice_sync(inv.name)
	return True


# --- log retention ----------------------------------------------------------


def cleanup_payment_logs(now=None) -> dict:
	"""Daily: prune Payment Attempt + Webhook Event logs past the retention window.

	These are high-volume append-only logs (one row per charge / per inbound
	callback). They are kept on a rolling window — Billing Settings'
	`payment_log_retention_days`, default 90 (~3 months) — and older rows are
	dropped. Statutory amounts live on the Invoice / ERPNext Sales Invoice (the
	SOR), so pruning the gateway log loses no money trail.

	A *live* record is never pruned: a non-terminal attempt (initiated/
	authorised), an attempt on an unsettled invoice (Open/Overdue), or one
	referenced by a Refund is kept regardless of age.
	"""
	days = settings.payment_log_retention_days()
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
		frappe.delete_doc(
			"Payment Attempt", a.name, ignore_permissions=True, force=True, delete_permanently=True
		)
		deleted += 1
	return deleted


def _prune_webhook_events(cutoff) -> int:
	"""Delete processed/ignored Webhook Event rows older than cutoff. Keep any not
	yet handled (received/failed) so a stuck event stays visible for triage."""
	stale = frappe.get_all(
		"Webhook Event",
		filters={"status": ["in", ("Processed", "Ignored")], "creation": ["<", cutoff]},
		pluck="name",
	)
	for name in stale:
		frappe.delete_doc("Webhook Event", name, ignore_permissions=True, force=True, delete_permanently=True)
	return len(stale)


def _extract_transaction_id(adapter_key: str, payload: dict):
	"""Pull the gateway transaction id out of a parsed webhook body."""
	if adapter_key == "Stripe":
		return ((payload.get("data") or {}).get("object") or {}).get("id")
	if adapter_key == "Razorpay":
		payment = (((payload.get("payload") or {}).get("payment") or {}).get("entity")) or {}
		return payment.get("id")
	return None


def _extract_failure(adapter_key: str, payload: dict) -> dict | None:
	"""Pull the decline detail out of a failure webhook body, normalised to
	{failure_code, decline_code, failure_reason, raw}. This is where an off-session
	decline's real reason lives — the sync charge response often can't see it."""
	if adapter_key == "Stripe":
		obj = ((payload.get("data") or {}).get("object")) or {}
		err = obj.get("last_payment_error") or {}
		if not err:
			return None
		return {
			"failure_code": err.get("code"),
			"decline_code": err.get("decline_code"),
			"failure_reason": err.get("message"),
			"raw": err,
		}
	if adapter_key == "Razorpay":
		entity = (((payload.get("payload") or {}).get("payment") or {}).get("entity")) or {}
		if not entity.get("error_code") and not entity.get("error_reason"):
			return None
		# Razorpay's error_reason is the granular bucket (payment_failed,
		# insufficient_balance, …) — the decline_code analogue.
		return {
			"failure_code": entity.get("error_code"),
			"decline_code": entity.get("error_reason"),
			"failure_reason": entity.get("error_description"),
			"raw": {
				k: entity.get(k)
				for k in ("error_code", "error_description", "error_reason", "error_source", "error_step")
			},
		}
	return None


def _retire_method_if_mandate_failed(attempt, failure_code):
	"""A mandate failure is not a decline to hold against the card.

	`payment_intent_mandate_invalid` and its siblings mean the standing permission
	is gone or the customer refused this debit at the bank. Retrying the same method
	cannot work, and the card may be perfectly good, so the method is retired and the
	customer is asked to authorise again (ADR 0023).
	"""
	from central.billing.payments import decline

	if not decline.is_mandate_failure(failure_code) or not attempt.payment_method:
		return
	method = frappe.get_doc("Payment Method", attempt.payment_method)
	if method.status == "Cancelled":
		return
	transition(method, "Cancelled", actor="gateway", reason=f"mandate failure: {failure_code}")
	method.reauth_required = 1
	method.save(ignore_permissions=True)

	from central.billing.payments import collection_mode

	collection_mode.trip(attempt.team, "mandate_failed")


def _stamp_failure(attempt, failure_code, decline_code, failure_reason, raw):
	"""Record the decline detail on a Payment Attempt. `raw` is stored as JSON on
	the Code field; failure_reason is trimmed to the Small Text column width."""
	attempt.failure_code = failure_code
	attempt.decline_code = decline_code
	attempt.failure_reason = (failure_reason or "")[:140] or None
	if raw:
		attempt.gateway_response = frappe.as_json(raw)


def _extract_topup(adapter_key: str, payload: dict):
	"""If this event is a wallet top-up (`purpose=wallet_topup` in the gateway
	notes/metadata set at create_topup_order), return its credit-able fields;
	else None. Amount is converted minor->major to match the credits ledger,
	mirroring confirm_topup's own `amount_total / 100`."""
	if adapter_key == "Razorpay":
		entity = (((payload.get("payload") or {}).get("payment") or {}).get("entity")) or {}
		notes = entity.get("notes") or {}
		if notes.get("purpose") != "wallet_topup":
			return None
		minor = entity.get("amount")
		return {
			"payment_id": entity.get("id"),
			"team": notes.get("team"),
			"amount": frappe.utils.flt(minor) / 100 if minor is not None else None,
			"currency": (entity.get("currency") or "").upper() or None,
			"gateway": adapter_key,
		}
	if adapter_key == "Stripe":
		obj = ((payload.get("data") or {}).get("object")) or {}
		notes = obj.get("metadata") or {}
		if notes.get("purpose") != "wallet_topup":
			return None
		minor = obj.get("amount_total") or obj.get("amount_received") or obj.get("amount")
		return {
			"payment_id": obj.get("payment_intent") or obj.get("id"),
			"team": notes.get("team"),
			"amount": frappe.utils.flt(minor) / 100 if minor is not None else None,
			"currency": (obj.get("currency") or "").upper() or None,
			"gateway": adapter_key,
		}
	return None


def _extract_invoice_payment(adapter_key: str, payload: dict):
	"""If this event is a hosted-checkout invoice payment (`purpose=invoice_payment`
	in the gateway notes/metadata set at create_invoice_checkout), return its invoice
	+ captured amount; else None. Mirrors _extract_topup for the wallet-topup case —
	a hosted invoice checkout carries no Payment Attempt, so it settles from notes."""
	if adapter_key == "Razorpay":
		entity = (((payload.get("payload") or {}).get("payment") or {}).get("entity")) or {}
		notes = entity.get("notes") or {}
		if notes.get("purpose") != "invoice_payment":
			return None
		minor = entity.get("amount")
		return {
			"invoice": notes.get("invoice"),
			"payment_id": entity.get("id"),
			"amount": frappe.utils.flt(minor) / 100 if minor is not None else None,
		}
	if adapter_key == "Stripe":
		obj = ((payload.get("data") or {}).get("object")) or {}
		notes = obj.get("metadata") or {}
		if notes.get("purpose") != "invoice_payment":
			return None
		minor = obj.get("amount_total") or obj.get("amount_received") or obj.get("amount")
		return {
			"invoice": notes.get("invoice"),
			"payment_id": obj.get("payment_intent") or obj.get("id"),
			"amount": frappe.utils.flt(minor) / 100 if minor is not None else None,
		}
	return None


def _settle_invoice_payment(event, inv_pay: dict) -> dict:
	"""Settle a hosted-checkout invoice from the capture webhook (idempotent on the
	invoice's Paid state). A malformed event (missing invoice/amount) is Ignored
	rather than settling a guess — an invoice never magically flips to Paid."""
	invoice = inv_pay.get("invoice")
	if not (invoice and inv_pay.get("amount") and frappe.db.exists("Invoice", invoice)):
		_mark_event(event, "Ignored")
		return {"handled": False, "reason": "invoice_payment_incomplete"}
	settled = _mark_invoice_paid(invoice, inv_pay["amount"])
	_mark_event(event, "Processed")
	return {"handled": True, "result": "paid", "invoice": invoice, "settled": settled}


def _credit_topup(event, topup: dict) -> dict:
	"""Book the wallet credit for a captured top-up, idempotent on the payment id.

	A malformed top-up (missing team/payment id/amount) is Ignored rather than
	crediting a guess — top-ups never magically credit."""
	if not (topup.get("team") and topup.get("payment_id") and topup.get("amount")):
		_mark_event(event, "Ignored")
		return {"handled": False, "reason": "topup_incomplete"}

	from central.billing.revenue import credits

	result = credits.purchase(
		topup["team"],
		topup["amount"],
		topup["currency"] or "INR",
		reference_name=topup["payment_id"],
		note=f"Wallet top-up ({topup['payment_id']})",
		gateway_payment_id=topup["payment_id"],
		gateway=topup.get("gateway"),
	)
	_mark_event(event, "Processed")
	return {
		"handled": True,
		"result": "topup_credited",
		"team": topup["team"],
		"payment_id": topup["payment_id"],
		"ledger_entry": result["ledger_entry"],
	}


def _mark_event(event, status: str):
	transition(event, status, actor="webhook", correlation=event.gateway_event_id)
	event.processed_at = frappe.utils.now_datetime()
	event.save(ignore_permissions=True)


def _notify(invoice, message: str):
	"""Log a billing notification (the #20 suite is the real sender)."""
	invoice.add_comment("Info", message)
