# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Retry / dunning + staged suspension (issue #14).

Failed-payment handling, end to end and time-staged off the invoice due date:

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

from central.billing.catalog import subscriptions
from central.billing.catalog.entitlements import issue_token

RETRY_DAYS = [1, 3, 7]
SUSPEND_AFTER_DAYS = 14
TERMINATE_AFTER_DAYS = 44


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

	days = (frappe.utils.getdate(now) - frappe.utils.getdate(inv.due_date)).days
	if days < RETRY_DAYS[0]:
		return {"invoice": invoice_name, "days_overdue": days, "action": "none"}

	from central.billing.catalog.subscriptions import anchor_subscription

	anchor = anchor_subscription(inv.team, inv.billing_group)
	sub = frappe.get_doc("Subscription", anchor) if anchor else None
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
	if days >= RETRY_DAYS[-1]:
		if inv.status == "Open":
			inv.db_set("status", "Overdue")
			actions.append("overdue")
			from central.billing.platform import notifications

			notifications.notify(
				inv.team, "Invoice Overdue", message=_overdue_message(invoice_name, mode),
				context={"invoice": invoice_name},
				reference_doctype="Invoice", reference_name=invoice_name,
			)
		if sub:
			standing = _advance_standing(anchor, "Past Due")

	# --- Day 14: suspend directive -> Agent stops --------------------------
	if days >= SUSPEND_AFTER_DAYS and sub:
		standing = _advance_standing(anchor, "Suspended")
		if standing == "Suspended" and not _active_directive(sub.team, "suspend"):
			issue_token(sub.team, {}, suspend=True)
			_notify(inv, f"Suspended for non-payment (day {days}); resource stopped, data preserved.")
			actions.append("suspend")

	# --- Day 44: terminate directive -> Agent terminates -------------------
	if days >= TERMINATE_AFTER_DAYS and sub and not _active_directive(sub.team, "terminate"):
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
