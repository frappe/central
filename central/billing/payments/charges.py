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
from central.billing.doctype.payment_attempt.payment_attempt import gateway_hold_active
from central.billing.gateways.base import GatewayError, GatewayTimeout, PaymentResult
from central.billing.payments.decline import Failure
from central.billing.platform.records import delete_billing_record, save_billing_record
from central.billing.states import transition

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
	"PAYMENT.CAPTURE.PENDING",  # PayPal: held for review or an eCheck; not paid yet
}
_SUCCESS_EVENTS = {
	"payment_intent.succeeded",
	"charge.succeeded",
	"payment.captured",
	"PAYMENT.CAPTURE.COMPLETED",
}
_FAILURE_EVENTS = {
	"payment_intent.payment_failed",
	# Stripe cancels an authorisation that expires uncaptured; it will never capture.
	"payment_intent.canceled",
	"charge.failed",
	"payment.failed",
	"PAYMENT.CAPTURE.DENIED",
}

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

	if in_flight := in_flight_attempt(invoice):
		return {"charged": False, "reason": "attempt_in_flight", "attempt": in_flight}

	method_name, gateway_name = _resolve_method(inv, payment_method, gateway)
	adapter = _adapter_for(gateway_name)

	# A debit the gateway can't pull silently in this currency (INR above ₹15,000 —
	# an RBI off-session rule that binds Stripe India and Razorpay alike) is never
	# attempted: it would just fail. An Auto Charge team is moved to Action Required so
	# it picks manual checkout / prepaid (ADR 0022, #106); a mode the customer already
	# chose is kept. An uncapped currency and anything under the ceiling pass through.
	if not adapter.can_charge_silently(frappe.utils.flt(inv.expected_collection), inv.currency):
		from central.billing.payments import collection_mode

		collection_mode.trip_auto_charge(inv.team, "invoice_over_threshold")
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
		)
		# Billing claims the charge for the system, and every link was just read from the database.
		attempt.insert(ignore_permissions=True, ignore_links=True)
	except _ALREADY_CLAIMED:
		# Someone else already claimed this exact charge (same invoice, same retry
		# number, so the same key). They own it; we don't start a second one. Undo
		# only the failed insert — whatever the caller did before this still stands.
		frappe.db.rollback(save_point=save_point)
		# By invoice and retry number, not a recomputed key: a key stored before the site
		# joined it would not match.
		owner = frappe.db.get_value(
			"Payment Attempt", {"invoice": invoice, "retry_number": retry_number}, "name"
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
	attempt.flags.ignore_links = True  # only its status and outcome change here
	method = frappe.get_doc("Payment Method", attempt.payment_method)
	adapter = _adapter_for(attempt.gateway)

	charge_input = frappe._dict(
		amount=frappe.utils.flt(attempt.amount),
		currency=attempt.currency,
		customer_id=method.gateway_customer_id,
		name=attempt.invoice,
		order_id=attempt.gateway_order_id,
	)
	try:
		if not attempt.gateway_order_id:
			# A gateway without a charge idempotency key (Razorpay) needs its order stored
			# before the payment is made, so a retry finds that payment instead of a new one.
			try:
				charge_input.order_id = adapter.prepare_charge(charge_input, attempt.name)
			except GatewayTimeout:
				raise
			except GatewayError as e:
				# The gateway refused to open the charge; nothing was taken.
				refused = PaymentResult(
					success=False, status="Failed", failure_code="order_refused", failure_reason=str(e)
				)
				return _record_result(attempt, refused)
			if charge_input.order_id:
				attempt.db_set("gateway_order_id", charge_input.order_id)
				_persist()
		result = adapter.charge(charge_input, method, attempt.idempotency_key)
	except GatewayTimeout as e:
		return _defer(attempt, e)
	return _record_result(attempt, result)


def _defer(attempt, e) -> dict:
	"""Transient: leave the attempt initiated so a retry reuses the same key."""
	attempt.failure_reason = str(e)[:140]
	save_billing_record(attempt)
	# We never reached the customer — a rate limit or a network fault is ours, not
	# theirs — so their retry ladder must not start ticking on it.
	from central.billing.revenue.dunning import defer_dunning

	defer_dunning(attempt.invoice, f"gateway unreachable: {str(e)[:80]}")
	_persist()
	return {"charged": False, "reason": "timeout", "attempt": attempt.name}


def _record_result(attempt, result) -> dict:
	"""Write down what the gateway answered for this attempt, and commit it."""
	attempt.gateway_transaction_id = result.gateway_transaction_id
	# The gateway is holding the charge on purpose — Stripe's India pre-debit window,
	# where the bank notifies the customer first and the money moves a day later. It
	# has neither succeeded nor failed, so the attempt stays in flight and nothing
	# retries or falls back against it (ADR 0023).
	if result.hold_until:
		attempt.gateway_hold_until = result.hold_until
		save_billing_record(attempt)
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
		stamp_failure(attempt, result.failure)
		transition(
			attempt, "Failed", actor="gateway", correlation=attempt.invoice, reason=attempt.failure_code
		)
		attempt.completed_at = frappe.utils.now_datetime()
		_retire_method_if_mandate_failed(attempt, result.failure_code)
	save_billing_record(attempt)
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
	"""Open a gateway order for an unpaid invoice the customer pays on-session.

	The Initiated attempt is claimed and committed under the invoice lock first, so a
	second click finds it in flight. The gateway is called after the lock is released,
	with the attempt as the receipt, and the gateway order id is stored on the attempt.
	The invoice is not touched here; it settles on the capture."""
	claim = _claim_on_session_attempt(invoice, gateway)
	if not claim.get("created"):
		return claim
	attempt = frappe.get_doc("Payment Attempt", claim["attempt"])
	gw_doc = frappe.get_doc("Payment Gateway", attempt.gateway)
	try:
		handles = _adapter_for(attempt.gateway).create_order(
			frappe.utils.flt(attempt.amount),
			attempt.currency,
			attempt.name,
			notes={"invoice": invoice, "team": attempt.team, "purpose": "invoice_payment"},
		)
	except Exception as e:
		fail_unopened_order(attempt, e)
		raise
	store_gateway_order(attempt, handles.get("order_id") or handles.get("payment_intent_id"))
	return {
		"created": True,
		"attempt": attempt.name,
		"gateway": attempt.gateway,
		"adapter_key": gw_doc.adapter_key,
		"amount": frappe.utils.flt(attempt.amount),
		"currency": attempt.currency,
		"receipt": attempt.name,
		**handles,
	}


def fail_unopened_order(attempt, error: Exception) -> None:
	"""The gateway did not open the order, so nothing can be paid against this attempt.
	Failing it frees the invoice for the next payment."""
	transition(attempt, "Failed", actor="gateway", correlation=attempt.invoice, reason="order not created")
	stamp_failure(attempt, {"failure_code": "order_not_created", "failure_reason": str(error)})
	# The paying member reads invoices but cannot write a Payment Attempt.
	save_billing_record(attempt)
	_persist()


def store_gateway_order(attempt, order_id: str) -> None:
	"""Commit the gateway order id before the payer gets the order. The capture webhook
	finds the attempt by this id, so it must outlive a crash in the rest of the request."""
	attempt.db_set("gateway_order_id", order_id)
	_persist()


def in_flight_attempt(invoice: str) -> str | None:
	"""An attempt occupying the invoice, so a second charge must not start beside it.

	A capture still waiting for its settlement counts. A capture already settled does not:
	if the invoice is still unpaid, that payment did not cover it and went to the wallet."""
	return _first_in_flight(invoice)


def unheld_attempt_in_flight(invoice: str) -> str | None:
	"""An attempt in flight that blocks credit from paying the invoice. A debit the gateway
	holds does not: credit may pay the invoice beside it, and the debit is refunded if it
	later goes through."""
	attempt = frappe.qb.DocType("Payment Attempt")
	return _first_in_flight(invoice, (attempt.status == "Captured") | ~gateway_hold_active(attempt))


def _first_in_flight(invoice: str, *conditions) -> str | None:
	attempt = frappe.qb.DocType("Payment Attempt")
	query = (
		frappe.qb.from_(attempt)
		.select(attempt.name)
		.where(attempt.invoice == invoice)
		.where(
			attempt.status.isin(["Initiated", "Authorised"])
			| ((attempt.status == "Captured") & attempt.completed_at.isnull())
		)
		.limit(1)
	)
	for condition in conditions:
		query = query.where(condition)
	rows = query.run(pluck=True)
	return rows[0] if rows else None


def _claim_on_session_attempt(invoice: str, gateway: str | None) -> dict:
	"""Lock the invoice, check it can be paid, and commit an Initiated attempt for it."""
	invoice_tbl = frappe.qb.DocType("Invoice")
	frappe.qb.from_(invoice_tbl).select(invoice_tbl.name).where(
		invoice_tbl.name == invoice
	).for_update().run()
	inv = frappe.get_doc("Invoice", invoice)

	if inv.status not in _UNSETTLED_INVOICE:
		return {"created": False, "reason": "not_open"}
	if frappe.utils.flt(inv.expected_collection) <= 0:
		return {"created": False, "reason": "nothing_due"}
	if in_flight := in_flight_attempt(invoice):
		return {"created": False, "reason": "attempt_in_flight", "attempt": in_flight}

	attempt = frappe.get_doc(
		{
			"doctype": "Payment Attempt",
			"invoice": invoice,
			"team": inv.team,
			"gateway": gateway or _gateway_for_invoice(inv),
			"amount": inv.expected_collection,
			"currency": inv.currency,
			"status": "Initiated",
			"initiated_at": frappe.utils.now_datetime(),
			"retry_number": frappe.db.count("Payment Attempt", {"invoice": invoice}),
		}
	).insert(ignore_permissions=True)
	_persist()
	return {"created": True, "attempt": attempt.name}


def confirm_invoice_payment(
	attempt: str,
	razorpay_order_id: str | None = None,
	razorpay_payment_id: str | None = None,
	razorpay_signature: str | None = None,
) -> dict:
	"""Verify the on-session checkout callback and settle the attempt it paid.

	The signature proves the payment and order ids go together. The payment is then read
	back from the gateway and must belong to this attempt's order and cover its amount,
	so a payment made for anything else settles nothing."""
	att = frappe.get_doc("Payment Attempt", attempt)
	adapter = _adapter_for(att.gateway)
	ok = adapter.verify_payment_signature(
		{
			"razorpay_order_id": razorpay_order_id,
			"razorpay_payment_id": razorpay_payment_id,
			"razorpay_signature": razorpay_signature,
		}
	)
	payment = adapter.verify_payment(razorpay_payment_id) if ok else None
	if not payment:
		frappe.throw(_("Payment confirmation failed."), frappe.ValidationError)
	return {"confirmed": True, **settle_checkout_attempt(att.name, payment)}


def settle_checkout_attempt(attempt: str, payment) -> dict:
	"""Settle a customer-present attempt with a payment the gateway confirmed for it.

	The payment must belong to the order Central created for this attempt and cover its
	amount; anything else settles nothing. Locked and idempotent, so the callback, the
	poll and the webhook settle it once."""
	frappe.db.get_value("Payment Attempt", attempt, "name", for_update=True)
	att = frappe.get_doc("Payment Attempt", attempt)
	if not (
		att.gateway_order_id
		and payment.order_id == att.gateway_order_id
		and payment.is_enough_for(att.amount, att.currency)
	):
		frappe.throw(_("Payment confirmation failed."), frappe.ValidationError)
	if att.status in _TERMINAL_ATTEMPT:
		return {"attempt": att.name, "status": att.status}

	att.gateway_transaction_id = payment.payment_id
	transition(att, "Captured", actor="gateway", correlation=att.invoice)
	att.completed_at = frappe.utils.now_datetime()
	save_billing_record(att)
	settled = _settle_invoice(att, payment)
	return {
		"attempt": att.name,
		"status": att.status,
		"settled": settled,
	}


def _gateway_for_invoice(inv) -> str:
	"""The gateway that settles this invoice's currency (on-session top-up rail)."""
	from central.billing.gateways.registry import resolve_gateway_for_currency

	return resolve_gateway_for_currency(inv.currency)


def _resolve_method(inv, payment_method, gateway):
	"""Method + gateway for the charge: explicit args, then the team's top
	chargeable Payment Method, then currency-based gateway lookup via the resolver.

	Deliberately `ordered_methods`, not `next_method_for`: this resolves a
	*default*, not a fallback rotation, so it must NOT exclude a method that
	already failed for this invoice — `pay_invoice` called twice (a manual retry)
	should resolve to the SAME method both times unless the caller says otherwise.
	"""
	if payment_method and gateway:
		return payment_method, gateway
	from central.billing.payments import collection

	methods = collection.ordered_methods(inv.team)
	method = methods[0] if methods else None
	method_name = payment_method or (method and method.name)
	gateway_name = gateway or (method and method.gateway)

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
	"""Apply a stored, signature-verified Webhook Event to the record Central stored for
	its payment: a Top-up Order, or a Payment Attempt on an invoice.

	The record is found by the gateway's ids (transaction, order, our receipt), never by
	payment notes. A success credits the top-up or settles the invoice for what was
	captured; reconciliation settles through the same path when a webhook is lost.
	"""
	event = frappe.get_doc("Webhook Event", event_name)
	event.flags.ignore_links = True  # only its status and outcome change here
	adapter_key = frappe.db.get_value("Payment Gateway", event.gateway, "adapter_key")
	payload = frappe.parse_json(event.raw_payload) if event.raw_payload else {}

	from central.billing.payments import disputes

	if disputes.is_dispute(event.event_type):
		result = disputes.apply_dispute(event, payload)
		_mark_event(event, "Processed" if result.get("handled") else "Ignored")
		return result

	from central.billing.gateways.registry import adapter_class

	payment = adapter_class(adapter_key).payment_from_event(payload)
	is_authorised = event.event_type in _AUTHORISED_EVENTS
	is_success = event.event_type in _SUCCESS_EVENTS
	is_failure = event.event_type in _FAILURE_EVENTS

	if not payment or not (is_authorised or is_success or is_failure):
		_mark_event(event, "Ignored")
		return {"handled": False, "reason": "not_a_charge_event"}

	# A payment settles only the record Central stored for it before the payer acted,
	# found by the gateway's own ids. Payment notes are never read: the payer sets them.
	from central.billing.doctype.top_up_order.top_up_order import TopupOrder

	decline = (_extract_failure(adapter_key, payload) or {}) if is_failure else None
	order = TopupOrder.for_payment(payment, event.gateway)
	if order:
		return _apply_topup_event(event, order, payment, is_success, decline)

	attempt_name = _attempt_for_payment(payment, event.gateway)
	if not attempt_name:
		return _apply_unmatched_event(event, payment, decline)

	return _apply_attempt_event(event, attempt_name, payment, is_authorised, decline)


def _apply_attempt_event(
	event, attempt_name: str, payment, is_authorised: bool, decline: dict | None
) -> dict:
	"""Hold, decline or settle the invoice attempt a charge event belongs to."""
	attempt = frappe.get_doc("Payment Attempt", attempt_name)
	attempt.flags.ignore_links = True  # only its status and outcome change here
	event.payment_attempt = attempt_name
	if is_authorised:
		# Funds held, capture pending. Advance only from initiated — never walk a
		# terminal attempt backwards if the capture/fail webhook arrived first.
		if attempt.status == "Initiated":
			transition(attempt, "Authorised", actor="webhook", correlation=attempt.invoice)
			save_billing_record(attempt)
		_mark_event(event, "Processed")
		return {"handled": True, "result": "Authorised", "attempt": attempt_name}

	if decline is not None:
		return _apply_attempt_failure(event, attempt, decline)

	if attempt.status in ("Captured", "Refunded") and attempt.completed_at:
		_mark_event(event, "Processed")  # already settled, by the callback or a replayed event
		return {"handled": True, "result": "duplicate", "attempt": attempt_name}
	attempt.gateway_transaction_id = payment.payment_id
	transition(attempt, "Captured", actor="webhook", correlation=attempt.invoice)
	attempt.completed_at = frappe.utils.now_datetime()
	attempt.resolved_by = "Webhook"
	save_billing_record(attempt)
	settled = _settle_invoice(attempt, payment)
	_mark_event(event, "Processed")
	return {"handled": True, "result": "paid", "invoice": attempt.invoice, "settled": settled}


def _apply_attempt_failure(event, attempt, decline: dict) -> dict:
	"""Fail an invoice attempt for its declined payment and try the team's next method."""
	fell_back = None
	# A failure matters only until the invoice is settled — never undo a Paid
	# invoice (a sync `captured` attempt isn't final: Paid lands on the success
	# webhook). Gate on invoice status, not attempt status, and act once.
	inv_status = frappe.db.get_value("Invoice", attempt.invoice, "status")
	if inv_status != "Paid" and attempt.status not in ("Failed", "Refunded"):
		transition(attempt, "Failed", actor="webhook", correlation=attempt.invoice)
		# Off-session declines surface their real reason here, not on the sync
		# charge response — pull it off the event so the attempt records why.
		stamp_failure(attempt, decline)
		attempt.completed_at = frappe.utils.now_datetime()
		save_billing_record(attempt)
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
	return {"handled": True, "result": "Failed", "attempt": attempt.name, "fell_back": fell_back}


def _attempt_for_payment(payment, gateway: str) -> str | None:
	"""The attempt a payment belongs to: by its transaction, by the order we created for
	it, or by our own receipt where only we can set it. An attempt on another gateway is
	not found."""
	for filters in (
		{"gateway_transaction_id": payment.payment_id},
		{"gateway_order_id": payment.order_id} if payment.order_id else None,
		{"name": payment.receipt} if payment.receipt else None,
	):
		if filters and (
			name := frappe.db.get_value("Payment Attempt", {**filters, "gateway": gateway}, "name")
		):
			return name
	return None


def _settle_invoice(attempt, payment=None) -> bool:
	"""Settle the attempt's invoice with what was captured. Without a gateway reading, what
	we charged off-session is what was captured. The attempt must already be saved as Captured."""
	adapter_key = frappe.db.get_value("Payment Gateway", attempt.gateway, "adapter_key")
	return _mark_invoice_paid(
		attempt,
		payment.amount if payment else attempt.amount,
		payment.currency if payment else attempt.currency,
		payment_id=payment.payment_id if payment else attempt.gateway_transaction_id,
		adapter_key=adapter_key,
	)


def _mark_invoice_paid(
	attempt, amount, currency: str, payment_id: str | None, adapter_key: str | None
) -> bool:
	"""Settle the attempt's invoice with a captured payment, under a row lock.

	1. A payment that lands on an invoice already Paid (by credit, or by another charge)
	   is refunded in full to its source, and an operator is told.
	2. A payment that lands on an invoice otherwise no longer unpaid is late money: it goes
	   to the wallet, and an operator is told.
	3. A payment in another currency, or for less than is due, settles nothing: it goes to
	   the wallet too, so captured money is never left without a ledger entry.
	4. Otherwise the invoice is Paid, and anything paid above what was due goes to the wallet.
	"""
	invoice_tbl = frappe.qb.DocType("Invoice")
	frappe.qb.from_(invoice_tbl).select(invoice_tbl.name).where(
		invoice_tbl.name == attempt.invoice
	).for_update().run()
	inv = frappe.get_doc("Invoice", attempt.invoice)
	inv.flags.ignore_links = True  # only its status and outcome change here
	due = frappe.utils.flt(inv.expected_collection)
	if inv.status == "Paid":
		_refund_to_source(inv, attempt)
		return False
	if unsettled := _unsettled_reason(inv, amount, currency, due):
		_to_wallet(inv, amount, currency, payment_id, adapter_key, unsettled)
		return False
	surplus = frappe.utils.flt(frappe.utils.flt(amount) - due, 2)
	if surplus > 0:
		_to_wallet(inv, surplus, currency, f"{payment_id}:surplus", adapter_key, "paid above what was due")
	inv.amount_paid = frappe.utils.flt(amount) - max(surplus, 0)
	inv.paid_at = frappe.utils.now_datetime()
	transition(
		inv,
		"Paid",
		reason="gateway capture settled",
		actor="webhook",
		correlation=inv.name,
		amount=inv.amount_paid,
	)
	save_billing_record(inv)

	from central.billing.platform import notifications

	notifications.notify(
		inv.team,
		"Payment Success",
		message=f"Invoice {inv.name} paid ({inv.amount_paid} {inv.currency or ''}).",
		reference_doctype="Invoice",
		reference_name=inv.name,
	)

	# Async, one-way, non-blocking push to the statutory SOR (#17).
	from central.billing.ingester.erpnext_sync import enqueue_invoice_sync

	enqueue_invoice_sync(inv.name)
	return True


def _unsettled_reason(inv, amount, currency: str, due: float) -> str | None:
	"""Why a captured payment cannot settle the invoice (rules 2 and 3 of _mark_invoice_paid)."""
	if inv.status not in _UNSETTLED_INVOICE:
		return "landed on a {0} invoice".format(inv.status)
	if (currency or "").upper() != (inv.currency or "").upper() or frappe.utils.flt(amount) + 0.005 < due:
		return f"did not cover {inv.currency} {due}"
	return None


def _to_wallet(inv, amount, currency: str, payment_id: str | None, adapter_key: str | None, why: str) -> None:
	"""Keep money the invoice cannot take as wallet credit, once per payment, and tell an operator."""
	from central.billing.revenue import credits

	if not payment_id or frappe.utils.flt(amount) <= 0:
		_flag_payment(inv, f"A payment of {currency} {amount} {why}, with no gateway id to credit it by.")
		return
	credits.purchase(
		inv.team,
		amount,
		currency,
		reference_name=payment_id,
		note=f"Payment for {inv.name} that {why}",
		gateway_payment_id=payment_id,
		gateway=adapter_key,
	)
	_flag_payment(inv, f"Payment {payment_id} of {currency} {amount} {why}; credited to the wallet.")


def _refund_to_source(inv, attempt) -> None:
	"""Give back a capture on an invoice that is already paid, in full, to where it came from.

	The invoice keeps the payment that settled it. This capture books no wallet credit and
	no advance, and its refund makes no credit note, because no invoice was issued against it."""
	from central.billing.payments import refunds

	refund = refunds.issue_refund(
		attempt.name, destination="Source", reason=f"{inv.name} was already paid", late_capture=True
	)
	attempt.reload()  # the refund moved the attempt to Refunded through its own copy
	outcome = "refunded to its source" if refund.status == "Completed" else "could not be refunded"
	_flag_payment(
		inv,
		f"Payment {attempt.gateway_transaction_id} of {attempt.currency} {attempt.amount} landed on "
		f"a paid invoice and {outcome} (Refund {refund.name}).",
	)


def _flag_payment(inv, message: str) -> None:
	"""Leave the problem on the invoice and in the operator alerts."""
	inv.add_comment("Info", message)
	frappe.log_error(title=f"Payment needs review on {inv.name}", message=message)


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
	"""Delete failed attempts older than cutoff, keeping any an open invoice still needs.

	A Captured or Refunded attempt is never deleted: a later refund or chargeback finds
	the charge through it, and the money trail must outlive any log window."""
	# Attempts referenced by a Refund anchor the refund audit chain — never drop.
	keep = set(frappe.get_all("Refund", pluck="payment_attempt") or [])
	candidates = frappe.get_all(
		"Payment Attempt",
		filters={"status": "Failed", "creation": ["<", cutoff]},
		fields=["name", "invoice"],
	)
	deleted = 0
	for a in candidates:
		if a.name in keep:
			continue
		if frappe.db.get_value("Invoice", a.invoice, "status") in _UNSETTLED_INVOICE:
			continue
		delete_billing_record(frappe.get_doc("Payment Attempt", a.name), force=True, delete_permanently=True)
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
		delete_billing_record(frappe.get_doc("Webhook Event", name), force=True, delete_permanently=True)
	return len(stale)


def _apply_topup_event(event, order, payment, is_success: bool, decline: dict | None) -> dict:
	"""Credit a top-up for its captured payment, or keep why its payment was declined."""
	if decline is not None:
		order.record_decline(decline, event.gateway_event_id)
		_mark_event(event, "Processed")
		return {"handled": True, "result": "topup_declined", "team": order.team}
	if not is_success:
		_mark_event(event, "Ignored")
		return {"handled": False, "reason": "topup_not_captured"}
	result = order.credit_wallet(payment)
	_mark_event(event, "Processed")
	return {"handled": True, "result": "topup_credited", "team": order.team, **result}


def _apply_unmatched_event(event, payment, decline: dict | None) -> dict:
	"""A payment with no top-up and no invoice attempt. A declined mandate authorisation
	is kept on the method it was for; anything else is not ours."""
	from central.billing.payments import payments

	method = None
	if decline is not None:
		method = payments.note_setup_payment_failure(event.gateway, payment.order_id, decline)
	if method:
		event.payment_method = method
		_mark_event(event, "Processed")
		return {"handled": True, "result": "setup_payment_declined", "payment_method": method}
	_mark_event(event, "Ignored")
	return {"handled": False, "reason": "no_matching_attempt"}


def _extract_failure(adapter_key: str, payload: dict) -> Failure | None:
	"""Pull the decline detail out of a failure webhook body, normalised to
	{failure_code, decline_code, failure_reason, raw}. This is where an off-session
	decline's real reason lives — the sync charge response often can't see it."""
	if adapter_key == "Stripe":
		obj = ((payload.get("data") or {}).get("object")) or {}
		err = obj.get("last_payment_error") or {}
		if not err and obj.get("cancellation_reason"):
			reason = obj["cancellation_reason"]
			return {
				"failure_code": "canceled",
				"decline_code": reason,
				"failure_reason": f"Stripe cancelled the payment ({reason})",
				"raw": {"cancellation_reason": reason},
			}
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


def stamp_failure(attempt, failure: Failure) -> None:
	"""Record the decline detail on a Payment Attempt. The gateway's `raw` answer is
	stored as JSON on the Code field."""
	from central.billing.payments import decline

	attempt.update(decline.failure_fields(failure))
	if failure.get("raw"):
		attempt.gateway_response = frappe.as_json(failure["raw"])


def _mark_event(event, status: str):
	transition(event, status, actor="webhook", correlation=event.gateway_event_id)
	event.processed_at = frappe.utils.now_datetime()
	save_billing_record(event)


def _notify(invoice, message: str):
	"""Log a billing notification (the #20 suite is the real sender)."""
	invoice.add_comment("Info", message)
