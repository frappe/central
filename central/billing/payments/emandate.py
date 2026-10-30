# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Off-session collection with the RBI pre-debit notice (ADR 0005, ADR 0022).

An Indian mandate may auto-debit silently only up to ₹15,000, and only AFTER a
pre-debit notification sent ≥24h before the debit. That is true of a Stripe India
card mandate and a Razorpay UPI Autopay mandate alike, because it is a rule about
the debit rather than about the provider. So collecting an `Auto Charge` team's
invoice is two-phase:

  1. schedule_predebit — notify the customer and stamp the earliest debit time
     (now + 24h) on the invoice. If the bill is over the silent ceiling it is NOT
     notified; it forks to Action Required instead (the manual/prepaid choice).
  2. charge_due — once the window has elapsed, run the off-session debit through
     the normal charge path, which re-checks the ₹15,000 ceiling (charges #50/1).

Both are idempotent and safe to re-run from the daily scheduler. The customer-side
heads-up is sent here; the bank's own RBI pre-debit notification is dispatched by
the gateway at debit time (an adapter concern, kept out of this orchestration).
"""

from datetime import datetime
from enum import StrEnum

import frappe

from central.billing.payments import collection, collection_mode
from central.billing.platform.jobs import each_isolated

PREDEBIT_NOTICE_HOURS = 24


class Predebit(StrEnum):
	"""What `await_predebit` tells the collector to do with one rail."""

	CHARGE_NOW = "charge_now"
	WAIT = "wait"
	ROTATE = "rotate"


def _is_notice_required(inv, gateway: str | None) -> bool:
	"""Whether the rail about to debit owes a notice: `gateway` when the caller names it,
	otherwise the team's own rail.

	It is a property of (gateway, currency), so an Indian mandate on Stripe owes one
	exactly as a Razorpay one does, and a USD card owes none.
	"""
	from central.billing.gateways import capabilities

	gateway, currency = (gateway, inv.currency) if gateway else collection_mode.team_rail(inv.team)
	return bool(gateway and currency and capabilities.requires_predebit_notice(gateway, currency))


def await_predebit(invoice: str, gateway: str, now: datetime | str | None = None) -> tuple[Predebit, dict]:
	"""What `gateway` may do with this invoice now under the pre-debit notice rule.

	1. CHARGE_NOW: the rail owes no notice, or the notice window has passed.
	2. WAIT: the notice is sent, now or before, and its window is still open. The
	   notice outcome comes with it.
	3. ROTATE: this rail cannot debit this invoice now (the mode holds debits back, or over the
	   silent ceiling), so the next method is tried instead of a window that never opens.
	"""
	inv = frappe.get_doc("Invoice", invoice)
	charge_after = inv.predebit_charge_after
	now_dt = frappe.utils.get_datetime(now) if now else frappe.utils.now_datetime()
	if not _is_notice_required(inv, gateway) or (
		charge_after and now_dt >= frappe.utils.get_datetime(charge_after)
	):
		return Predebit.CHARGE_NOW, {}
	notice = schedule_predebit(invoice, now=now_dt, gateway=gateway)
	if notice.get("notified") or notice.get("skipped") == "already_notified":
		return Predebit.WAIT, notice
	return Predebit.ROTATE, notice


def schedule_predebit(invoice: str, now=None, gateway: str | None = None) -> dict:
	"""Send the pre-debit notice for an e-mandate invoice and arm its debit window.
	Over the silent ceiling → fork to Action Required rather than promise a debit we
	can't make off-session. Idempotent (skips an already-notified invoice).

	`gateway` is the rail about to debit, when the caller knows it (a fallback onto a
	second rail); otherwise the team's own rail decides."""
	inv = frappe.get_doc("Invoice", invoice)
	if not collection_mode.is_debit_allowed(inv.team):
		return {"invoice": invoice, "skipped": "debit_not_allowed"}
	if not _is_notice_required(inv, gateway):
		# A rail that debits without a notice is collected by the ordinary sweep. Arming
		# a 24h window here would delay every international charge for nothing.
		return {"invoice": invoice, "skipped": "no_notice_required"}
	if inv.invoice_type != "Billable" or inv.status not in ("Open", "Overdue"):
		return {"invoice": invoice, "skipped": "not_collectable"}
	if frappe.utils.flt(inv.expected_collection) <= 0:
		return {"invoice": invoice, "skipped": "nothing_due"}
	if inv.predebit_notified_at:
		return {"invoice": invoice, "skipped": "already_notified"}

	# A bill over the silent ceiling can't be debited off-session — fork to the
	# customer's choice (manual checkout / prepaid) instead of notifying a debit
	# that would fail.
	st = collection_mode.evaluate(
		inv.team,
		projected_amount=frappe.utils.flt(inv.expected_collection),
		reason="invoice_over_threshold",
	)
	if st["action_required"]:
		return {"invoice": invoice, "skipped": "over_threshold", "action_required": True}

	now_dt = frappe.utils.get_datetime(now) if now else frappe.utils.now_datetime()
	charge_after = frappe.utils.add_to_date(now_dt, hours=PREDEBIT_NOTICE_HOURS)
	frappe.db.set_value(
		"Invoice",
		invoice,
		{"predebit_notified_at": now_dt, "predebit_charge_after": charge_after},
		update_modified=False,
	)

	from central.billing.platform import notifications

	notifications.notify(
		inv.team,
		"Pre-debit Notice",
		context={
			"invoice": invoice,
			"amount": f"{frappe.utils.flt(inv.expected_collection)} {inv.currency or ''}".strip(),
			"charge_on": frappe.utils.format_datetime(charge_after),
		},
		reference_doctype="Invoice",
		reference_name=invoice,
	)
	return {"invoice": invoice, "notified": True, "charge_after": str(charge_after)}


def charge_due(now=None) -> list[dict]:
	"""Off-session debit every e-mandate invoice whose pre-debit window has elapsed.
	The charge path re-checks the ₹15,000 ceiling (#50 item 1)."""
	now_dt = frappe.utils.get_datetime(now) if now else frappe.utils.now_datetime()
	due = frappe.get_all(
		"Invoice",
		filters=[
			["invoice_type", "=", "Billable"],
			["status", "in", ["Open", "Overdue"]],
			["expected_collection", ">", 0],
			["predebit_charge_after", "is", "set"],
			["predebit_charge_after", "<=", now_dt],
		],
		fields=["name", "team"],
	)
	auto = [inv.name for inv in due if collection_mode.is_debit_allowed(inv.team)]
	return each_isolated(
		"E-mandate debit",
		"Invoice",
		auto,
		lambda name: {"invoice": name, **collection.collect_invoice(name, now=now_dt)},
	)


def run_emandate_cycle(now=None) -> dict:
	"""Daily scheduler: arm the pre-debit notice on new e-mandate invoices, then
	debit the ones whose window has elapsed."""
	pending = frappe.get_all(
		"Invoice",
		filters=[
			["invoice_type", "=", "Billable"],
			["status", "in", ["Open", "Overdue"]],
			["expected_collection", ">", 0],
			["predebit_notified_at", "is", "not set"],
		],
		pluck="name",
	)
	notified = each_isolated(
		"Pre-debit notice", "Invoice", pending, lambda name: schedule_predebit(name, now=now)
	)
	return {"notified": notified, "charged": charge_due(now=now)}
