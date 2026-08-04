# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Retry / dunning + staged suspension (issue #14).

Failed-payment handling, end to end and time-staged off the invoice due date. The
days below are the shipped defaults; the ladder itself is configured on Billing
Settings, so the stages are read per run rather than fixed here:

  Day 1 / 3 / 7   retry the charge (each a new Payment Attempt), notify with the
                  failure reason.
  Day 7 (exhausted)   invoice -> Overdue, standing -> past_due. KEEP RUNNING
                      (grace) — being late is not yet being cut off.
  Day 14 (continued)  suspend directive on the entitlement-token channel (cap 0
                      + suspend) -> standing suspended -> the Agent stops the
                      resource (data preserved).
  Day 44 (~30d suspended)   terminate directive -> the Agent terminates.

Only a deliberate directive ever stops a resource. Central being unreachable
does not — the Agent keeps running on a stale token (see entitlement.enforcement
_state on the Agent).
"""

import frappe

from central.billing import settings
from central.billing.catalog import subscriptions
from central.billing.catalog.entitlements import issue_token
from central.billing.states import transition


def defer_dunning(invoice: str, reason: str) -> bool:
	"""Push an invoice's dunning clock forward — we failed to ask, so they aren't late.

	Every stage below is counted from a date the customer is entitled to assume we
	honoured: that we tried to collect when we said we would. When the attempt fails
	on *our* side — the gateway rate-limited us, the run backed up, a worker died
	mid-charge — the customer did nothing wrong, and starting their retry ladder,
	their Overdue notice and their suspension countdown on that date would be
	charging them for our outage.

	So the clock restarts at today plus the same window a freshly opened invoice
	gets. Monotonic (it only ever moves forward) and self-limiting (a successful
	ask stops pushing it), so a permanently broken gateway cannot defer collection
	forever — it defers *escalation*, while reconciliation and the next run keep
	trying. `due_date` is untouched: what the customer owes and when they owed it is
	an accounting fact, and AR aging must keep telling the truth.
	"""
	fair_start = frappe.utils.add_days(frappe.utils.nowdate(), settings.invoice_due_days())
	current = frappe.db.get_value("Invoice", invoice, "dunning_starts_on")
	if current and frappe.utils.getdate(current) >= frappe.utils.getdate(fair_start):
		return False
	frappe.db.set_value("Invoice", invoice, "dunning_starts_on", fair_start)
	frappe.logger("billing").info(f"dunning for {invoice} deferred to {fair_start}: {reason}")
	return True


def dunning_clock_start(invoice_doc):
	"""The date this invoice's retry ladder counts from.

	`dunning_starts_on` is absent on invoices raised before it existed, and on any
	invoice whose collection went to plan — in both cases the due date is the
	honest answer.
	"""
	return invoice_doc.get("dunning_starts_on") or invoice_doc.due_date


def _notify(invoice, message: str):
	invoice.add_comment("Info", message)


def _collection_mode(team: str) -> str | None:
	"""The team's collection mode (ADR 0005), or None for a team with no profile."""
	return frappe.db.get_value("Billing Profile", team, "collection_mode")


def _overdue_message(invoice: str, mode: str | None) -> str:
	"""Mode-aware overdue copy: tell the customer the action that settles it."""
	if mode == "Manual Checkout":
		return f"Invoice {invoice} is overdue — pay it now to avoid suspension."
	if mode == "Prepaid":
		return f"Invoice {invoice} is overdue — top up your wallet to settle it and avoid suspension."
	return f"Invoice {invoice} is overdue. Please settle it to avoid suspension."


def retry_payment(invoice_name: str) -> dict:
	"""One dunning retry: charge the next untried method (primary→backup, #28),
	notified with the reason on failure."""
	from central.billing.payments import collection
	from central.billing.platform import notifications

	result = collection.collect_invoice(invoice_name)
	last = frappe.get_all(
		"Payment Attempt", {"invoice": invoice_name}, order_by="creation desc", limit=1, pluck="name"
	)
	if last:
		attempt = frappe.get_doc("Payment Attempt", last[0])
		if attempt.status == "Failed":
			n = frappe.db.count("Payment Attempt", {"invoice": invoice_name})
			reason = attempt.failure_reason or attempt.failure_code or "declined"
			notifications.notify(
				attempt.team, "Payment Retry",
				message=f"Payment retry {n} for invoice {invoice_name} failed: {reason}",
				reference_doctype="Invoice", reference_name=invoice_name,
			)
	return result


def _advance_standing(subscription: str, target: str):
	"""Move standing toward `target` if the direct transition is legal; the
	stepwise caller guarantees ordering (current -> past_due -> suspended)."""
	current = frappe.db.get_value("Subscription", subscription, "account_standing")
	if current == target:
		return current
	try:
		subscriptions.set_standing(subscription, target, changed_by="dunning")
		return target
	except subscriptions.InvalidTransition:
		return current


def _active_directive(team: str, field: str) -> bool:
	"""True if the team's latest token already carries this directive."""
	name = frappe.db.get_value(
		"Entitlement Token", {"team": team}, "name", order_by="creation desc"
	)
	return bool(name and frappe.db.get_value("Entitlement Token", name, field))


def process_invoice_dunning(invoice_name: str, now=None) -> dict:
	"""Drive one invoice through the dunning stages for the current date.

	Idempotent per day: re-running on the same day does not double-retry or
	re-issue a directive already in force.
	"""
	inv = frappe.get_doc("Invoice", invoice_name)
	if inv.invoice_type != "Billable":
		return {"invoice": invoice_name, "skipped": "Cost Report"}
	if inv.status not in ("Open", "Overdue") or frappe.utils.flt(inv.expected_collection) <= 0:
		return {"invoice": invoice_name, "skipped": "nothing_due"}
	if not inv.due_date:
		return {"invoice": invoice_name, "skipped": "no_due_date"}

	days = (frappe.utils.getdate(now) - frappe.utils.getdate(dunning_clock_start(inv))).days
	retry_days = settings.dunning_retry_days()
	# With no retries configured there is nothing to wait for, so the invoice goes
	# Overdue on day zero and the ladder below carries on from there.
	overdue_after = retry_days[-1] if retry_days else 0
	if retry_days and days < retry_days[0]:
		return {"invoice": invoice_name, "days_overdue": days, "action": "none"}

	sub = frappe.get_doc("Subscription", inv.subscription) if inv.subscription else None
	actions = []

	# --- retries: try the next untried method, if any (escalate, don't repeat,
	# #28). Once every method has failed there is nothing left to charge, so the
	# stages below escalate. Credits-only teams (no methods) skip straight there.
	from central.billing.payments import collection

	# Off-session retries only make sense for an auto-charge mode. manual_checkout
	# (customer pays on-session) and action_required (paused at the ₹15k threshold)
	# are never silently retried — dunning just escalates and asks them to act
	# (ADR 0005, #50). prepaid/stripe_auto/emandate retry iff a method exists.
	mode = _collection_mode(inv.team)
	auto_charge = mode not in ("Manual Checkout", "Action Required")
	if inv.status == "Open" and auto_charge and collection.next_method_for(invoice_name, inv.team):
		retry_payment(invoice_name)
		actions.append("retry")
		inv.reload()
		if inv.status == "Paid":
			return {"invoice": invoice_name, "days_overdue": days, "action": "paid"}

	standing = sub.account_standing if sub else None

	# --- Day 7: Overdue + past_due, still running --------------------------
	if days >= overdue_after:
		if inv.status == "Open":
			transition(inv, "Overdue", reason="dunning: past due window elapsed", actor="scheduler")
			inv.save(ignore_permissions=True)
			actions.append("overdue")
			from central.billing.platform import notifications

			notifications.notify(
				inv.team, "Invoice Overdue", message=_overdue_message(invoice_name, mode),
				context={"invoice": invoice_name},
				reference_doctype="Invoice", reference_name=invoice_name,
			)
		if sub:
			standing = _advance_standing(inv.subscription, "Past Due")

	# --- Day 14: suspend directive -> Agent stops --------------------------
	if days >= settings.suspend_after_days() and sub:
		standing = _advance_standing(inv.subscription, "Suspended")
		if standing == "Suspended" and not _active_directive(sub.team, "suspend"):
			issue_token(sub.team, {}, suspend=True)
			_notify(inv, f"Suspended for non-payment (day {days}); resource stopped, data preserved.")
			from central.notifications import create_notification

			create_notification(
				inv.team, "Server suspended for non-payment",
				category="Server", event_type="Server Suspended", severity="Error",
				message=f"A server was suspended after {days} days overdue on invoice {invoice_name}. "
				"Data is preserved — settle the invoice to restore it.",
				reference_doctype="Invoice", reference_name=invoice_name,
				action_label="Pay now", action_route="/billing/invoices",
			)
			actions.append("suspend")

	# --- Day 44: terminate directive -> Agent terminates -------------------
	if days >= settings.terminate_after_days() and sub and not _active_directive(sub.team, "terminate"):
		issue_token(sub.team, {}, suspend=True, terminate=True)
		_notify(inv, f"Terminated after the suspension window (day {days}).")
		actions.append("terminate")

	return {"invoice": invoice_name, "days_overdue": days, "actions": actions, "standing": standing}


def run_dunning(now=None) -> list[dict]:
	"""Daily scheduler: dun every unpaid, due billable invoice."""
	invoices = frappe.get_all(
		"Invoice",
		filters=[
			["invoice_type", "=", "Billable"],
			["status", "in", ["Open", "Overdue"]],
			["expected_collection", ">", 0],
		],
		pluck="name",
	)
	return [process_invoice_dunning(name, now=now) for name in invoices]
