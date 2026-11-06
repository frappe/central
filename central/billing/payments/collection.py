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

from datetime import datetime

import frappe
from frappe import _

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


def get_teams_with_retry_rail(teams: set[str]) -> set[str]:
	"""The teams dunning can charge off-session before any attempt: the collection mode allows a
	debit (`collection_mode.is_debit_allowed`) and a chargeable method is on file (`ordered_methods`).
	Two queries for any number of teams."""
	from central.billing.payments import collection_mode

	if not teams:
		return set()
	held = frappe.get_all(
		"Billing Profile",
		filters={"name": ["in", list(teams)], "collection_mode": ["in", collection_mode.DEBIT_HELD_MODES]},
		pluck="name",
	)
	allowed = teams.difference(held)
	if not allowed:
		return set()
	return set(
		frappe.get_all(
			"Payment Method",
			filters={"team": ["in", list(allowed)], "status": "Active", "reauth_required": 0},
			pluck="team",
			distinct=True,
		)
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


def collect_invoice(invoice: str, new_round: bool = False, now: datetime | str | None = None) -> dict:
	"""Charge the next untried method; rotate immediately on a synchronous decline.

	Idempotent and safe to re-enter (from settlement, a webhook failure, or a
	dunning retry): the in-flight guard + invoice row lock in charges.pay_invoice
	prevent a double charge, and the per-invoice failed-set guarantees each method
	is tried at most once per round. `new_round` starts a dunning retry round, and
	`now` is the clock a pre-debit window is read against.
	"""
	from central.billing.revenue.tax import is_internal_team

	inv = frappe.get_doc("Invoice", invoice)
	if is_internal_team(inv.team):
		return {"collected": False, "reason": "internal_team"}
	earlier = attempts_of(invoice) if new_round else None
	skipped = set()
	while True:
		outcome = _charge_next_method(inv, earlier, skipped, now)
		if outcome is not None:
			return outcome


def collect_on_payment_date(now: datetime | str | None = None) -> list[dict]:
	"""Hourly: charge on the payment date, and remind the day before.

	1. Make the first debit on each pre-debit rail whose window has opened (`emandate.charge_due`).
	2. Start collection on each invoice that has reached its payment date, or will reach
	   it tomorrow, and has no payment attempt. A rail that owes a pre-debit notice sends
	   it a day early. An invoice that missed its payment date is still picked up.
	3. Retry each invoice whose ladder has the single retry, 24 hours after its first charge
	   failed (`dunning.run_single_retries`).
	4. Remind each team whose invoice is charged tomorrow (`payment_notices`).

	Step 1 runs first. An invoice it charged has an attempt, so step 2 skips it.
	"""
	from central.billing.payments import emandate, payment_notices
	from central.billing.revenue import dunning

	now_dt = frappe.utils.get_datetime(now) if now else frappe.utils.now_datetime()
	debited = emandate.charge_due(now=now_dt)
	collected = _collect_first_charges(now_dt)
	retried = dunning.run_single_retries(now_dt)
	reminded = payment_notices.send_payment_reminders(now_dt)
	return [*debited, *collected, *retried, *reminded]


def _collect_first_charges(now_dt: datetime) -> list[dict]:
	"""Start collection on every owed invoice whose payment date is tomorrow or earlier and
	that has no payment attempt yet."""
	from central.billing.doctype.invoice.invoice import owed_filters
	from central.billing.platform.jobs import each_isolated

	waiting = frappe.get_all(
		"Invoice",
		filters=[
			*owed_filters(),
			["invoice_type", "=", "Billable"],
			["expected_collection", ">", 0],
			["payment_date", "<=", frappe.utils.add_days(now_dt.date(), 1)],
		],
		pluck="name",
	)
	tried = set(
		frappe.get_all("Payment Attempt", filters={"invoice": ["in", waiting]}, pluck="invoice")
		if waiting
		else []
	)
	return each_isolated(
		"Collect on payment date",
		"Invoice",
		[name for name in waiting if name not in tried],
		lambda name: {"invoice": name, **collect_invoice(name, now=now_dt)},
	)


def payment_starts_at(inv) -> datetime:
	"""The first moment the invoice may be debited: the start of its payment date."""
	# Every opened invoice gets a payment date, so a missing one is corrupt data. It must
	# not read as today and let the card be charged early.
	if not inv.get("payment_date"):
		frappe.throw(
			_("Invoice {0} is open but has no payment date.").format(inv.name), frappe.ValidationError
		)
	return frappe.utils.get_datetime(inv.payment_date)


def _is_before_payment_date(inv, gateway: str, now: datetime | str | None = None) -> bool:
	"""Whether a debit on `gateway` must still wait for the invoice's payment date.

	1. On or after the payment date, no rail waits.
	2. Before it, a rail that owes a pre-debit notice goes on, so the notice goes out no
	   earlier than 24 hours before. Its debit window never opens before the payment date.
	3. Before it, every other rail waits.
	"""
	from central.billing.payments import emandate

	now_dt = frappe.utils.get_datetime(now) if now else frappe.utils.now_datetime()
	return now_dt < payment_starts_at(inv) and not emandate.is_notice_required(inv, gateway)


def _charge_next_method(
	inv, earlier: set | None, skipped: set, now: datetime | str | None = None
) -> dict | None:
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

	if _is_before_payment_date(inv, method.gateway, now):
		return {"collected": False, "reason": "before_payment_date"}

	# Every off-session debit on a rail that owes a pre-debit notice waits for it, whichever
	# path asked for it: the billing run, a dunning retry or a webhook.
	predebit, notice = emandate.await_predebit(inv.name, method.gateway, now)
	if predebit == emandate.Predebit.WAIT:
		return {"collected": False, "reason": "awaiting_predebit_window", **notice}
	if predebit == emandate.Predebit.ROTATE:
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
