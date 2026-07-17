# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Reconciliation — the charged-but-never-webhooked safety net (issue #21).

The single most important hardening job: a webhook can be lost, so a charge that
succeeded at the gateway might never settle. This daily scan asks the gateway what
really happened to every attempt stuck in an ambiguous state, and drives it to a
terminal state on the gateway's answer rather than on a guess of ours.

Terminal-state model (the resolved HITL decision — see issue #21):

  ambiguous = {initiated, authorised}     terminal = {captured, failed, refunded}
  grace 30 min (let the webhook arrive) · alert after 24 h
  gateway success  -> settle via charges._settle_invoice (idempotent), captured
  gateway failure  -> failed (dunning retries; invoice stays Open)
  no transaction id -> we never heard back at all: re-send the same request with its
                       original key, which the gateway either replays or performs
                       (ADR 0017). Too old for the key to dedupe -> alert, don't guess.
  still pending     -> leave; alert ops past the threshold
  provenance: resolved_by = reconciliation (vs webhook)

A second, symmetric hole: the sync charge path lands an attempt at Captured and
defers settlement to the capture webhook. If that webhook is lost the invoice is
stranded Open with money already taken, and — being terminal — the attempt is
invisible to the ambiguous scan. reconcile_captured_attempt re-confirms success
at the gateway and settles it through the same idempotent path.
"""

import frappe

_AMBIGUOUS = ("Initiated", "Authorised")
_GATEWAY_SUCCESS = {"succeeded", "captured", "paid", "completed"}
_GATEWAY_FAILED = {"failed", "canceled", "cancelled", "declined", "expired", "voided"}
# A Captured attempt whose invoice sits in one of these lost its settlement webhook.
_UNSETTLED_INVOICE = ("Open", "Overdue")

GRACE_MINUTES = 30
ALERT_AFTER_HOURS = 24
# A gateway forgets an idempotency key after about a day. Inside that window, re-sending
# a charge is deduped by the gateway; outside it, the same request would be a second one.
KEY_REPLAY_HOURS = 24


def _adapter(gateway: str):
	from central.billing.gateways.registry import get_adapter

	return get_adapter(frappe.get_doc("Payment Gateway", gateway))


def reconcile_attempt(attempt_name: str, now=None) -> dict:
	"""Resolve one ambiguous Payment Attempt against gateway truth (read-only)."""
	attempt = frappe.get_doc("Payment Attempt", attempt_name)
	if attempt.status not in _AMBIGUOUS:
		return {"attempt": attempt_name, "skipped": "already_terminal"}

	if not attempt.gateway_transaction_id:
		return _resolve_unanswered(attempt, now)

	status = (_adapter(attempt.gateway).get_transaction_status(attempt.gateway_transaction_id) or "").lower()

	if status in _GATEWAY_SUCCESS:
		_resolve_paid(attempt)
		return {"attempt": attempt_name, "resolved": "paid", "gateway_status": status}
	if status in _GATEWAY_FAILED:
		_resolve_failed(attempt, f"gateway:{status}")
		return {"attempt": attempt_name, "resolved": "Failed", "gateway_status": status}

	# Still pending/unknown at the gateway — escalate if it has aged out.
	now = frappe.utils.get_datetime(now or frappe.utils.now_datetime())
	started = frappe.utils.get_datetime(attempt.initiated_at or attempt.creation)
	age_hours = frappe.utils.time_diff_in_hours(now, started)
	if age_hours >= ALERT_AFTER_HOURS:
		_alert_ops(attempt, status)
		return {"attempt": attempt_name, "unresolved": status, "alerted": True}
	return {"attempt": attempt_name, "unresolved": status}


def reconcile_captured_attempt(attempt_name: str, now=None) -> dict:
	"""Settle a Captured attempt whose invoice was never marked Paid (read-only).

	The sync charge path (charges.pay_invoice) advances an attempt to Captured the
	moment the gateway reports success, then leaves settlement to the capture
	webhook. If that webhook is lost the money is taken but the invoice is stranded
	Open — and the ambiguous-state scan never looks at a terminal (Captured)
	attempt. This closes that hole: re-confirm success at the gateway, then settle
	through the same idempotent path the webhook uses.
	"""
	attempt = frappe.get_doc("Payment Attempt", attempt_name)
	if attempt.status != "Captured":
		return {"attempt": attempt_name, "skipped": "not_captured"}

	inv_status = frappe.db.get_value("Invoice", attempt.invoice, "status")
	if inv_status not in _UNSETTLED_INVOICE:
		return {"attempt": attempt_name, "skipped": "invoice_settled"}

	# Captured is local state; reconciliation only ever settles on fresh gateway
	# truth. Without a confirmed success we don't guess — settle nothing.
	status = ""
	if attempt.gateway_transaction_id:
		status = (_adapter(attempt.gateway).get_transaction_status(attempt.gateway_transaction_id) or "").lower()
	if status not in _GATEWAY_SUCCESS:
		now = frappe.utils.get_datetime(now or frappe.utils.now_datetime())
		started = frappe.utils.get_datetime(attempt.initiated_at or attempt.creation)
		if frappe.utils.time_diff_in_hours(now, started) >= ALERT_AFTER_HOURS:
			_alert_ops(attempt, status or "unknown")
			return {"attempt": attempt_name, "unresolved": status, "alerted": True}
		return {"attempt": attempt_name, "unresolved": status}

	from central.billing.payments import charges

	settled = charges._settle_invoice(attempt)
	if not attempt.completed_at or not attempt.resolved_by:
		attempt.completed_at = attempt.completed_at or frappe.utils.now_datetime()
		attempt.resolved_by = attempt.resolved_by or "Reconciliation"
		attempt.save(ignore_permissions=True)
	return {"attempt": attempt_name, "resolved": "paid", "gateway_status": status, "settled": settled}


def run_reconciliation(now=None) -> list:
	"""Daily scan: resolve aged ambiguous attempts, then settle any captured-but-
	open invoice whose capture webhook never landed."""
	now = frappe.utils.get_datetime(now or frappe.utils.now_datetime())
	cutoff = frappe.utils.add_to_date(now, minutes=-GRACE_MINUTES)
	stuck = frappe.get_all(
		"Payment Attempt",
		filters=[["status", "in", list(_AMBIGUOUS)], ["initiated_at", "<=", cutoff]],
		pluck="name",
	)
	results = [reconcile_attempt(name, now=now) for name in stuck]

	unsettled = _captured_unsettled_attempts(cutoff)
	results += [reconcile_captured_attempt(name, now=now) for name in unsettled]
	return results


def _captured_unsettled_attempts(cutoff) -> list:
	"""Captured attempts aged past the grace window whose invoice is still Open/
	Overdue — a settlement webhook that never arrived. One join, no N+1."""
	PA = frappe.qb.DocType("Payment Attempt")
	INV = frappe.qb.DocType("Invoice")
	return (
		frappe.qb.from_(PA)
		.join(INV)
		.on(PA.invoice == INV.name)
		.select(PA.name)
		.where(
			(PA.status == "Captured")
			& (PA.initiated_at <= cutoff)
			& (INV.status.isin(_UNSETTLED_INVOICE))
		)
	).run(pluck=True)


def _resolve_unanswered(attempt, now=None) -> dict:
	"""An attempt with no transaction id: we asked the gateway to charge and never
	wrote down an answer. From here we cannot tell whether the money moved.

	A card charge we started off-session can be re-sent with its original key. The
	gateway replays the first charge if it happened and performs it if it didn't, so
	either way there is exactly one charge and the attempt ends terminal.

	Once the key is too old for the gateway to dedupe on, re-sending would be a second
	charge, so we stop and ask a human. Marking it Failed instead would be worse: the
	next retry mints a new key, and the card gets charged twice.
	"""
	now = frappe.utils.get_datetime(now or frappe.utils.now_datetime())
	started = frappe.utils.get_datetime(attempt.initiated_at or attempt.creation)
	age_hours = frappe.utils.time_diff_in_hours(now, started)

	if not attempt.payment_method:
		# A customer-present checkout that was never completed. No money can move
		# without the customer, and there is nothing to re-send.
		_resolve_failed(attempt, "checkout never completed")
		return {"attempt": attempt.name, "resolved": "Failed", "reason": "no_txn"}

	if age_hours >= KEY_REPLAY_HOURS:
		_alert_ops(attempt, "no transaction id, too old to re-send safely")
		return {"attempt": attempt.name, "unresolved": "unanswered", "alerted": True}

	from central.billing.payments import charges

	charges.resume_attempt(attempt.name)
	status = frappe.db.get_value("Payment Attempt", attempt.name, "status")
	if status == "Captured":
		# The gateway has the money (ours or a replay of the original). Settle through
		# the same idempotent path the webhook uses.
		_resolve_paid(frappe.get_doc("Payment Attempt", attempt.name))
	return {"attempt": attempt.name, "resolved": status, "replayed": True}


def _resolve_paid(attempt):
	"""Settle through the same idempotent path a webhook uses; tag provenance."""
	from central.billing.payments import charges

	attempt.status = "Captured"
	attempt.completed_at = frappe.utils.now_datetime()
	attempt.resolved_by = "Reconciliation"
	attempt.save(ignore_permissions=True)
	charges._settle_invoice(attempt)  # idempotent: a duplicate webhook would no-op too


def _resolve_failed(attempt, reason: str):
	attempt.status = "Failed"
	attempt.completed_at = frappe.utils.now_datetime()
	attempt.resolved_by = "Reconciliation"
	attempt.failure_reason = reason[:140]
	attempt.save(ignore_permissions=True)


def _alert_ops(attempt, gateway_status: str):
	frappe.log_error(
		title=f"Reconciliation: unresolved attempt {attempt.name}",
		message=(
			f"Payment Attempt {attempt.name} (invoice {attempt.invoice}) has been "
			f"{attempt.status} for >= {ALERT_AFTER_HOURS}h; gateway reports "
			f"'{gateway_status}'. Manual review needed."
		),
	)
	if attempt.invoice:
		try:
			frappe.get_doc("Invoice", attempt.invoice).add_comment(
				"Info", f"Reconciliation could not resolve attempt {attempt.name} (gateway: {gateway_status})."
			)
		except Exception:  # noqa: BLE001
			pass
