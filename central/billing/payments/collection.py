# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Settlement fallback: primary -> backup payment methods (issue #28).

A team keeps an ordered list of active methods (Payment Method.priority). When
credits don't cover a bill, settlement charges the primary and, on failure,
rotates to the next method. Because a charge is confirmed asynchronously (the
invoice goes Paid only on the webhook, see charges.py), fallback is
event-driven, not a synchronous try/except cascade:

- A decline arrives synchronously (PaymentResult.success == False) or later as a
  webhook failure event. Both funnel into `collect_invoice`.
- `collect_invoice` charges the next active, non-re-auth method that has NOT
  already failed for this invoice (the "already failed" set is read from the
  invoice's Payment Attempt rows — no extra state).
- Immediate fallback: a synchronous decline rotates to the next method in the
  same run; a synchronous success (captured) stops and waits for the webhook.
- Escalate, don't repeat: each method is tried at most once per collection round.
  Once all have failed, `collect_invoice` returns no_method and the invoice is left
  Open for dunning (#14). Each dunning retry day starts a new round, in which a
  method whose decline can clear (a shortfall, a generic refusal) is charged again.
  A hard decline (expired, lost, fraud, revoked mandate) is never charged again.
"""

import frappe

from central.billing.payments import charges, decline


def ordered_methods(team: str) -> list:
	"""A team's chargeable methods, primary first. Skips non-active and methods
	whose mandate needs re-authorisation."""
	return frappe.get_all(
		"Payment Method",
		filters={"team": team, "status": "Active", "reauth_required": 0},
		order_by="priority asc, creation asc",
		fields=["name", "gateway", "priority"],
	)


def attempts_of(invoice: str) -> set:
	"""Every payment attempt made for this invoice so far."""
	return set(frappe.get_all("Payment Attempt", filters={"invoice": invoice}, pluck="name"))


def _failed_methods_for(invoice: str, earlier: set | None = None) -> set:
	"""Methods that failed this invoice. With `earlier`, the attempts made before this
	round, only this round's failures count, and failures no later round can fix."""
	attempts = frappe.get_all(
		"Payment Attempt",
		filters={"invoice": invoice, "status": "Failed"},
		fields=["name", "payment_method", "failure_code", "decline_code"],
	)
	return {
		a.payment_method
		for a in attempts
		if earlier is None
		or a.name not in earlier
		or not decline.is_retryable_later(a.failure_code, a.decline_code)
	}


def next_method_for(invoice: str, team: str, earlier: set | None = None, skip: set | None = None):
	"""The next untried, chargeable method for this invoice, or None if exhausted.
	`earlier` starts a new round, as in `_failed_methods_for`. `skip` holds methods that
	cannot be charged in this run."""
	passed_over = _failed_methods_for(invoice, earlier) | (skip or set())
	for method in ordered_methods(team):
		if method.name not in passed_over:
			return method
	return None


def _ask_for_another_method(inv) -> None:
	"""Tell a customer we have run out of ways to charge them.

	Only after something has actually been tried and refused. A team that has never
	added a method is already being asked elsewhere (onboarding, the Action Required
	banner), and this notification would be the third voice saying it.

	The engine dedupes on unread notifications for the same event and invoice, so a
	dunning run that re-enters here daily does not repeat itself.
	"""
	tried = frappe.get_all("Payment Attempt", filters={"invoice": inv.name, "status": "Failed"}, limit=1)
	if not tried:
		return

	from central.billing.platform import notifications

	notifications.notify(
		inv.team,
		"Add Payment Method",
		reference_doctype="Invoice",
		reference_name=inv.name,
	)


def collect_invoice(invoice: str, new_round: bool = False) -> dict:
	"""Charge the next untried method; rotate immediately on a synchronous decline.

	Idempotent and safe to re-enter (from settlement, a webhook failure, or a
	dunning retry): the in-flight guard + invoice row lock in charges.pay_invoice
	prevent a double charge, and the per-invoice failed-set guarantees each method
	is tried at most once per round. `new_round` starts a dunning retry round.
	"""
	from central.billing.revenue.tax import is_internal_team

	inv = frappe.get_doc("Invoice", invoice)
	if is_internal_team(inv.team):
		return {"collected": False, "reason": "internal_team"}
	earlier = attempts_of(invoice) if new_round else None
	skipped = set()
	while True:
		outcome = _charge_next_method(inv, earlier, skipped)
		if outcome is not None:
			return outcome


def _charge_next_method(inv, earlier: set | None, skipped: set) -> dict | None:
	"""Try the next method once. Returns the outcome to stop on, or None to rotate to the
	next method (a final decline, or a rail that cannot debit now, added to `skipped`)."""
	from central.billing.payments import emandate

	if in_flight := charges.in_flight_attempt(inv.name):
		return {"collected": False, "reason": "attempt_in_flight", "attempt": in_flight}

	method = next_method_for(inv.name, inv.team, earlier, skip=skipped)
	if not method:
		# Every method has failed (or there are none) — leave it for dunning, and
		# ask the customer for another way to pay. Off-session there is nobody to
		# offer the other rail to in the moment, so the ask has to arrive as a
		# notification instead (ADR 0022 §5, ADR 0023).
		_ask_for_another_method(inv)
		return {"collected": False, "reason": "no_method"}

	# Every off-session debit on a rail that owes a pre-debit notice waits for it, whichever
	# path asked for it: the billing run, a dunning retry or a webhook.
	predebit, notice = emandate.await_predebit(inv.name, method.gateway)
	if predebit == emandate.WAIT:
		return {"collected": False, "reason": "awaiting_predebit_window", **notice}
	if predebit == emandate.ROTATE:
		skipped.add(method.name)
		return None

	result = charges.pay_invoice(inv.name, method.name, method.gateway)

	# A synchronous decline: rotate to the next method now (immediate fallback) —
	# but only when the decline is final. An ambiguous failure may still settle at
	# the gateway, and charging a second method on top of it pays one invoice
	# twice; reconciliation resolves those instead (ADR 0022).
	if result.get("status") != "Failed":
		# Captured (awaiting webhook), in-flight, or a transient timeout: stop here.
		return result
	if not decline.is_terminal(result.get("failure_code")):
		return {"collected": False, "reason": "ambiguous_failure", "attempt": result.get("attempt")}
	return None
