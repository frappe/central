# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Retry / dunning + staged suspension (issue #14).

Failed-payment handling, end to end. The first charge is made on the invoice's payment
date by the hourly collection sweep. The ladder below counts from that date (the
anchor, `dunning_starts_on`). The days are the shipped defaults of Billing Settings:

  Retries         every 2 days after the anchor, while the retry date is on or before
                  the invoice due date. When no retry fits, one retry 1 day after the
                  anchor. Each is a new Payment Attempt, notified with the reason.
  Last retry day  invoice -> Overdue, standing -> past_due. KEEP RUNNING (grace).
  Suspension      on the invoice's `suspends_on`: the 15th of the month it opened in.
                  Every server subscription -> suspended, and Central stops the team's
                  running servers (data preserved). Paying the invoice returns the team
                  to current and starts them again (`subscriptions.restore_after_payment`).
  Termination     10 days after suspension: the operator alerts page a person, who
                  decides. Nothing is deleted automatically.

Only dunning stops a server for non-payment, and only a payment starts it again.
"""

import frappe

from central.billing import settings
from central.billing.catalog import subscriptions
from central.billing.doctype.billing_profile.billing_profile import (
	LAST_PAYMENT_DAY,
	get_due_date,
	get_payment_date,
	get_suspension_date,
	get_suspension_date_after,
)
from central.billing.doctype.invoice.invoice import OUTSTANDING, UNSETTLED, is_issued, owed_filters
from central.billing.platform.jobs import each_isolated
from central.billing.platform.records import save_billing_record
from central.billing.states import transition


def defer_dunning(invoice: str, reason: str) -> bool:
	"""Move an invoice's ladder anchor forward to today: we failed to ask, so they aren't late.

	Every stage is counted from a date the customer is entitled to assume we honoured:
	that we tried to collect when we said we would. When the attempt fails on *our* side
	(the gateway rate-limited us, the run backed up, a worker died mid-charge), the
	retries, the Overdue notice and the suspension move forward by the same number of
	days. Monotonic (it only ever moves forward) and self-limiting (a successful ask
	stops pushing it). `due_date` is untouched: it is an accounting fact AR aging reads.
	"""
	row = frappe.db.get_value(
		"Invoice", invoice, ["payment_date", "due_date", "dunning_starts_on", "suspends_on"], as_dict=True
	)
	dates = get_ladder_dates(row)
	today = frappe.utils.getdate(frappe.utils.nowdate())
	if dates.anchor >= today:
		return False

	shift = (today - dates.anchor).days
	suspends_on = frappe.utils.add_days(dates.suspends_on, shift)
	frappe.db.set_value("Invoice", invoice, {"dunning_starts_on": today, "suspends_on": suspends_on})
	frappe.logger("billing").info(f"dunning for {invoice} deferred to {today}: {reason}")
	return True


def get_ladder_dates(invoice) -> frappe._dict:
	"""The dates the ladder of an issued invoice is drawn from.

	`invoice` is a document or a dict with `payment_date`, `due_date`, `dunning_starts_on`
	and `suspends_on`. The retry window end is the due date, moved forward by as many days
	as `defer_dunning` moved the anchor. An invoice without `suspends_on` gets the date
	the opening run stores, read from the month of its payment date.
	"""
	due_date = frappe.utils.getdate(invoice.get("due_date"))
	payment_date = frappe.utils.getdate(invoice.get("payment_date") or due_date)
	anchor = frappe.utils.getdate(invoice.get("dunning_starts_on") or payment_date)
	shift = max(0, (anchor - payment_date).days)
	suspends_on = invoice.get("suspends_on")
	if not suspends_on:
		suspends_on = frappe.utils.add_days(get_suspension_date_after(payment_date, due_date), shift)

	return frappe._dict(
		anchor=anchor,
		retry_until=frappe.utils.getdate(frappe.utils.add_days(due_date, shift)),
		suspends_on=frappe.utils.getdate(suspends_on),
	)


def get_opening_ladder_dates(team: str, opened_on) -> frappe._dict:
	"""The ladder dates of an invoice that would open for `team` on `opened_on`."""
	return frappe._dict(
		anchor=get_payment_date(team, opened_on),
		retry_until=get_due_date(team, opened_on),
		suspends_on=get_suspension_date(team, opened_on),
	)


def is_dunning_deferred(invoice) -> bool:
	"""`defer_dunning` moved the anchor past the payment date: collection failed on our side."""
	anchor = invoice.get("dunning_starts_on")
	payment_date = invoice.get("payment_date") or invoice.get("due_date")
	return bool(anchor and payment_date) and frappe.utils.getdate(anchor) > frappe.utils.getdate(payment_date)


def dunning_policy() -> frappe._dict:
	"""The ladder's settings, read once."""
	return frappe._dict(
		retry_interval=settings.dunning_retry_interval_days(),
		terminate_after=settings.terminate_after_days(),
	)


def get_last_payment_day_with_retries() -> int:
	"""The last payment day whose first interval retry still falls on or before the due date
	of an invoice opened on the 1st. A later payment day gets one retry, 1 day after it."""
	interval = settings.dunning_retry_interval_days()
	due_day = 1 + settings.invoice_due_days()
	days = [day for day in range(1, LAST_PAYMENT_DAY + 1) if day + interval <= max(due_day, day)]
	return max(days, default=0)


# Stages that land on the same day still have an order: a retry is attempted before
# the invoice is declared overdue, and suspension precedes termination.
_STAGE_ORDER = {"Retry": 0, "Overdue": 1, "Suspend": 2, "Terminate": 3}


def dunning_schedule(dates: frappe._dict, policy=None) -> list[frappe._dict]:
	"""The dated ladder for an invoice with these ladder `dates` (`get_ladder_dates`).

	Pure date arithmetic over the dates and the policy: no document reads and no writes.
	`process_invoice_dunning` executes this schedule; anything that wants to *show* the
	ladder without running it reads the same list. Each stage's `day` counts from the anchor.

	Pass an explicit `policy` to ask what a different ladder would do.
	"""
	policy = policy or dunning_policy()
	anchor = frappe.utils.getdate(dates.anchor)
	retries = _retry_dates(anchor, dates.retry_until, policy.retry_interval)
	suspends_on = frappe.utils.getdate(dates.suspends_on)

	stages = [frappe._dict(stage="Retry", attempt=n, date=on) for n, on in enumerate(retries, start=1)]
	stages.append(frappe._dict(stage="Overdue", date=retries[-1]))
	stages.append(frappe._dict(stage="Suspend", date=suspends_on))
	stages.append(
		frappe._dict(
			stage="Terminate",
			date=frappe.utils.getdate(frappe.utils.add_days(suspends_on, policy.terminate_after)),
		)
	)

	for stage in stages:
		stage.day = (stage.date - anchor).days
	return sorted(stages, key=lambda s: (s.date, _STAGE_ORDER[s.stage]))


def _retry_dates(anchor, retry_until, interval: int) -> list:
	"""Every `interval` days after the anchor up to `retry_until`, or one retry the next day."""
	retry_until = frappe.utils.getdate(retry_until)
	interval = max(1, frappe.utils.cint(interval))
	dates = []
	retry_on = frappe.utils.getdate(frappe.utils.add_days(anchor, interval))
	while retry_on <= retry_until:
		dates.append(retry_on)
		retry_on = frappe.utils.getdate(frappe.utils.add_days(retry_on, interval))
	return dates or [frappe.utils.getdate(frappe.utils.add_days(anchor, 1))]


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


def _retry_if_due(inv, schedule, now) -> dict | None:
	"""Run the collection round of the latest retry day reached, once. Returns its result.

	Manual Checkout (paid on-session) and Action Required (paused at the ₹15k threshold)
	are not retried off-session; dunning escalates and asks them to act (ADR 0005). Every
	other mode, Prepaid included, is retried."""
	if not has_retry_rail(inv, inv.team):
		return None
	if not is_retry_due(inv.name, schedule, now):
		return None
	return retry_payment(inv.name)


def has_retry_rail(invoice, team: str) -> bool:
	"""Dunning can retry the invoice off-session. `invoice` carries its name and status.

	1. The invoice is Outstanding. Dunning never retries an Overdue invoice.
	2. The team's collection mode allows an off-session debit.
	3. A chargeable method is left to try in a new round."""
	from central.billing.payments import collection, collection_mode

	if invoice.status != OUTSTANDING or not collection_mode.is_debit_allowed(team):
		return False
	attempts = collection.attempts_of(invoice.name)
	return bool(collection.next_method_for(invoice.name, team, attempts))


def is_retry_due(invoice: str, schedule: list, now) -> bool:
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
	if inv.status not in UNSETTLED or frappe.utils.flt(inv.expected_collection) <= 0:
		return {"invoice": invoice_name, "skipped": "nothing_due"}
	if not is_issued(inv):
		return {"invoice": invoice_name, "skipped": "no_due_date"}

	dates = get_ladder_dates(inv)
	days = (frappe.utils.getdate(now) - dates.anchor).days
	schedule = dunning_schedule(dates)
	reached = stages_reached(schedule, now)
	if "Retry" not in reached:
		return {"invoice": invoice_name, "days_overdue": days, "action": "none"}

	from central.billing.catalog.subscriptions import anchor_subscription

	anchor = anchor_subscription(inv.team)
	sub = frappe.get_doc("Subscription", anchor) if anchor else None
	actions = []

	# --- retries: one collection round per retry day (escalate, don't repeat, #28).
	# Credits-only teams (no methods) skip straight to the stages below.
	mode = _collection_mode(inv.team)
	if _retry_if_due(inv, schedule, now):
		actions.append("retry")
		inv.reload()
		if inv.status == "Paid":
			return {"invoice": invoice_name, "days_overdue": days, "action": "paid"}

	standing = sub.account_standing if sub else None

	# --- last retry day: Overdue + past_due, still running -----------------
	if "Overdue" in reached:
		if inv.status == OUTSTANDING:
			transition(inv, "Overdue", reason="dunning: past due window elapsed", actor="scheduler")
			save_billing_record(inv)
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
			subscriptions.mark_past_due(inv.team)
			standing = frappe.db.get_value("Subscription", anchor, "account_standing")

	# --- suspension date: suspend -> stop the team's running servers --------
	if "Suspend" in reached and sub:
		if subscriptions.suspend_for_nonpayment(inv.team):
			standing = "Suspended"
			_notify(
				inv,
				f"Suspended for non-payment on {dates.suspends_on}; running servers stopped, data preserved.",
			)
			from central.notification import engine

			engine.dispatch(
				inv.team,
				"server_suspended",
				message=f"Your account was suspended because invoice {invoice_name} is unpaid. "
				"Running servers were stopped and data is preserved. Pay the invoice to restore them.",
				reference_doctype="Invoice",
				reference_name=invoice_name,
			)
			actions.append("suspend")

	# --- termination date: an operator decides; nothing is deleted here.
	# platform/alerts.termination_due pages them while the invoice stays unpaid.
	if "Terminate" in reached and sub:
		actions.append("termination_due")

	return {"invoice": invoice_name, "days_overdue": days, "actions": actions, "standing": standing}


def run_dunning(now=None) -> list[dict]:
	"""Daily scheduler: dun every unpaid, due billable invoice. An internal team is never dunned."""
	from central.billing.revenue.invoicing.lifecycle import settle_internal_teams

	settle_internal_teams()
	filters = [*owed_filters(), ["invoice_type", "=", "Billable"], ["expected_collection", ">", 0]]
	internal = frappe.get_all("Billing Profile", filters={"is_internal": 1}, pluck="team")
	if internal:
		filters.append(["team", "not in", internal])
	invoices = frappe.get_all("Invoice", filters=filters, pluck="name")
	return each_isolated("Dunning", "Invoice", invoices, lambda name: process_invoice_dunning(name, now=now))
