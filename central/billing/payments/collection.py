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
- Escalate, don't repeat: each method is tried at most once per invoice. Once
  all have failed, `collect_invoice` returns no_method and the invoice is left
  Open for dunning (#14) to escalate — it never re-charges a failed method.
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


def _failed_methods_for(invoice: str) -> set:
	"""Methods that already produced a failed attempt for this invoice."""
	return set(
		frappe.get_all(
			"Payment Attempt",
			filters={"invoice": invoice, "status": "Failed"},
			pluck="payment_method",
		)
	)


def next_method_for(invoice: str, team: str):
	"""The next untried, chargeable method for this invoice, or None if exhausted."""
	failed = _failed_methods_for(invoice)
	for method in ordered_methods(team):
		if method.name not in failed:
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


def collect_invoice(invoice: str) -> dict:
	"""Charge the next untried method; rotate immediately on a synchronous decline.

	Idempotent and safe to re-enter (from settlement, a webhook failure, or a
	dunning retry): the in-flight guard + invoice row lock in charges.pay_invoice
	prevent a double charge, and the per-invoice failed-set guarantees each method
	is tried at most once.
	"""
	inv = frappe.get_doc("Invoice", invoice)

	while True:
		in_flight = frappe.get_all(
			"Payment Attempt",
			filters={"invoice": invoice, "status": ["in", charges._IN_FLIGHT]},
			pluck="name",
		)
		if in_flight:
			return {"collected": False, "reason": "attempt_in_flight", "attempt": in_flight[0]}

		method = next_method_for(invoice, inv.team)
		if not method:
			# Every method has failed (or there are none) — leave it for dunning, and
			# ask the customer for another way to pay. Off-session there is nobody to
			# offer the other rail to in the moment, so the ask has to arrive as a
			# notification instead (ADR 0022 §5, ADR 0023).
			_ask_for_another_method(inv)
			return {"collected": False, "reason": "no_method"}

		result = charges.pay_invoice(invoice, method.name, method.gateway)

		# A synchronous decline: rotate to the next method now (immediate fallback) —
		# but only when the decline is final. An ambiguous failure may still settle at
		# the gateway, and charging a second method on top of it pays one invoice
		# twice; reconciliation resolves those instead (ADR 0022).
		if result.get("status") == "Failed":
			if not decline.is_terminal(result.get("failure_code")):
				return {"collected": False, "reason": "ambiguous_failure", "attempt": result.get("attempt")}
			continue
		# Captured (awaiting webhook), in-flight, or a transient timeout: stop here.
		return result
