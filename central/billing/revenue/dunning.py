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
  Day 14 (continued)  every server subscription -> suspended, and Central stops
                      the team's running servers (data preserved). Paying the
                      invoice returns the team to current and starts them again
                      (`subscriptions.restore_after_payment`).
  Day 44 (~30d suspended)   termination is due: the operator alerts page a person,
                            who decides. Nothing is deleted automatically.

Only dunning stops a server for non-payment, and only a payment starts it again.
"""

import frappe

from central.billing import settings
from central.billing.catalog import subscriptions
from central.billing.platform.jobs import each_isolated
from central.billing.platform.records import mark_billing_write
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


def dunning_policy() -> frappe._dict:
	"""The ladder's knobs, read once.

	`overdue_after` is not its own setting — the invoice falls overdue once the last
	retry has been spent, so with no retries configured there is nothing to wait for
	and it goes overdue on day zero.
	"""
	retry_days = settings.dunning_retry_days()
	return frappe._dict(
		retry_days=retry_days,
		overdue_after=retry_days[-1] if retry_days else 0,
		suspend_after=settings.suspend_after_days(),
		terminate_after=settings.terminate_after_days(),
	)


# Stages that land on the same day still have an order: a retry is attempted before
# the invoice is declared overdue, and suspension precedes termination.
_STAGE_ORDER = {"Retry": 0, "Overdue": 1, "Suspend": 2, "Terminate": 3}


def dunning_schedule(clock_start, policy=None) -> list[frappe._dict]:
	"""The dated ladder for an invoice whose dunning clock starts on `clock_start`.

	Pure date arithmetic over the policy — no document reads, no writes, and no
	knowledge of any particular invoice. `process_invoice_dunning` executes this
	schedule; anything that wants to *show* the ladder without running it (which
	dates, which stage, when the resource stops) reads the same list.

	Pass an explicit `policy` to ask what a different ladder would do.
	"""
	policy = policy or dunning_policy()
	start = frappe.utils.getdate(clock_start)
	stages = [
		frappe._dict(stage="Retry", attempt=n, day=day) for n, day in enumerate(policy.retry_days, start=1)
	]
	stages.append(frappe._dict(stage="Overdue", day=policy.overdue_after))
	stages.append(frappe._dict(stage="Suspend", day=policy.suspend_after))
	stages.append(frappe._dict(stage="Terminate", day=policy.terminate_after))

	for s in stages:
		s.date = frappe.utils.add_days(start, s.day)
	return sorted(stages, key=lambda s: (s.day, _STAGE_ORDER[s.stage]))


def stages_reached(schedule: list, on) -> set:
	"""The stage names whose date has arrived by `on`."""
	today = frappe.utils.getdate(on)
	return {s.stage for s in schedule if frappe.utils.getdate(s.date) <= today}


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
	"""One dunning retry: a new collection round, primary→backup (#28), notified with
	the reason on failure."""
	from central.billing.payments import collection
	from central.billing.platform import notifications

	result = collection.collect_invoice(invoice_name, new_round=True)
	last = frappe.get_all(
		"Payment Attempt", {"invoice": invoice_name}, order_by="creation desc", limit=1, pluck="name"
	)
	if last:
		attempt = frappe.get_doc("Payment Attempt", last[0])
		if attempt.status == "Failed":
			n = frappe.db.count("Payment Attempt", {"invoice": invoice_name})
			reason = attempt.failure_reason or attempt.failure_code or "declined"
			notifications.notify(
				attempt.team,
				"Payment Retry",
				message=f"Payment retry {n} for invoice {invoice_name} failed: {reason}",
				reference_doctype="Invoice",
				reference_name=invoice_name,
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


def _retry_if_due(inv, schedule, now, mode: str | None) -> dict | None:
	"""Run the collection round of the latest retry day reached, once. Returns its result.

	Off-session retries only make sense for an auto-charge mode. Manual Checkout (paid
	on-session) and Action Required (paused at the ₹15k threshold) are never silently
	retried; dunning escalates and asks them to act (ADR 0005)."""
	from central.billing.payments import collection

	if inv.status != "Open" or mode in ("Manual Checkout", "Action Required"):
		return None
	if not _is_retry_due(inv.name, schedule, now):
		return None
	if not collection.next_method_for(inv.name, inv.team, collection.attempts_of(inv.name)):
		return None
	return retry_payment(inv.name)


def _is_retry_due(invoice: str, schedule: list, now) -> bool:
	"""A retry day has been reached and no charge was tried on or after it.

	A run that missed retry days catches up with one round, not one per missed day, so a
	backlog never charges the same card several times in one run."""
	days = [
		s.date
		for s in schedule
		if s.stage == "Retry" and frappe.utils.getdate(s.date) <= frappe.utils.getdate(now)
	]
	if not days:
		return False
	start = frappe.utils.get_datetime(frappe.utils.getdate(days[-1]))
	return not frappe.db.exists("Payment Attempt", {"invoice": invoice, "creation": [">=", start]})


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

	clock_start = dunning_clock_start(inv)
	days = (frappe.utils.getdate(now) - frappe.utils.getdate(clock_start)).days
	policy = dunning_policy()
	schedule = dunning_schedule(clock_start, policy)
	reached = stages_reached(schedule, now)
	if policy.retry_days and "Retry" not in reached:
		return {"invoice": invoice_name, "days_overdue": days, "action": "none"}

	from central.billing.catalog.subscriptions import anchor_subscription

	anchor = anchor_subscription(inv.team)
	sub = frappe.get_doc("Subscription", anchor) if anchor else None
	actions = []

	# --- retries: one collection round per retry day (escalate, don't repeat, #28).
	# Credits-only teams (no methods) skip straight to the stages below.
	mode = _collection_mode(inv.team)
	if _retry_if_due(inv, schedule, now, mode):
		actions.append("retry")
		inv.reload()
		if inv.status == "Paid":
			return {"invoice": invoice_name, "days_overdue": days, "action": "paid"}

	standing = sub.account_standing if sub else None

	# --- Day 7: Overdue + past_due, still running --------------------------
	if "Overdue" in reached:
		if inv.status == "Open":
			transition(inv, "Overdue", reason="dunning: past due window elapsed", actor="scheduler")
			# The scheduled dunning transition owns this invoice state change.
			mark_billing_write(inv).save(ignore_permissions=True)
			actions.append("overdue")
			from central.billing.platform import notifications

			notifications.notify(
				inv.team,
				"Invoice Overdue",
				message=_overdue_message(invoice_name, mode),
				context={"invoice": invoice_name},
				reference_doctype="Invoice",
				reference_name=invoice_name,
			)
		if sub:
			standing = _advance_standing(anchor, "Past Due")

	# --- Day 14: suspend -> stop the team's running servers ------------------
	if "Suspend" in reached and sub:
		if subscriptions.suspend_for_nonpayment(inv.team):
			standing = "Suspended"
			_notify(inv, f"Suspended for non-payment (day {days}); running servers stopped, data preserved.")
			from central.notification import engine

			engine.dispatch(
				inv.team,
				"server_suspended",
				message=f"Your account was suspended after {days} days overdue on invoice {invoice_name}. "
				"Running servers were stopped and data is preserved. Pay the invoice to restore them.",
				reference_doctype="Invoice",
				reference_name=invoice_name,
			)
			actions.append("suspend")

	# --- Day 44: termination is due. An operator decides; nothing is deleted here.
	# platform/alerts.termination_due pages them while the invoice stays unpaid.
	if "Terminate" in reached and sub:
		actions.append("termination_due")

	return {"invoice": invoice_name, "days_overdue": days, "actions": actions, "standing": standing}


def run_dunning(now=None) -> list[dict]:
	"""Daily scheduler: dun every unpaid, due billable invoice. An internal team is never dunned."""
	from central.billing.revenue.invoicing.lifecycle import settle_internal_teams

	settle_internal_teams()
	filters = [
		["invoice_type", "=", "Billable"],
		["status", "in", ["Open", "Overdue"]],
		["expected_collection", ">", 0],
	]
	internal = frappe.get_all("Tax Profile", filters={"is_internal": 1}, pluck="team")
	if internal:
		filters.append(["team", "not in", internal])
	invoices = frappe.get_all("Invoice", filters=filters, pluck="name")
	return each_isolated("Dunning", "Invoice", invoices, lambda name: process_invoice_dunning(name, now=now))
