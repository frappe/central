# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""E-mandate off-session collection with the RBI pre-debit notice (#50 item 3, ADR 0005).

An Indian e-mandate (Razorpay UPI Autopay / card mandate) may auto-debit silently
only up to ₹15,000, and only AFTER a pre-debit notification sent ≥24h before the
debit. So collecting an `emandate` team's invoice is two-phase:

  1. schedule_predebit — notify the customer and stamp the earliest debit time
     (now + 24h) on the invoice. If the bill is over the silent ceiling it is NOT
     notified; it forks to Action Required instead (the manual/prepaid choice).
  2. charge_due — once the window has elapsed, run the off-session debit through
     the normal charge path, which re-checks the ₹15,000 ceiling (charges #50/1).

Both are idempotent and safe to re-run from the daily scheduler. The customer-side
heads-up is sent here; the bank's own RBI pre-debit notification is dispatched by
the gateway at debit time (a Razorpay adapter concern, kept out of this orchestration).
"""

import frappe

from central.billing.payments import collection, collection_mode

PREDEBIT_NOTICE_HOURS = 24


def schedule_predebit(invoice: str, now=None) -> dict:
	"""Send the pre-debit notice for an e-mandate invoice and arm its debit window.
	Over the silent ceiling → fork to Action Required rather than promise a debit we
	can't make off-session. Idempotent (skips an already-notified invoice)."""
	inv = frappe.get_doc("Invoice", invoice)
	if frappe.db.get_value("Billing Profile", inv.team, "collection_mode") != "E-Mandate":
		return {"invoice": invoice, "skipped": "not_emandate"}
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
		inv.team, projected_amount=frappe.utils.flt(inv.expected_collection),
		reason="invoice_over_threshold",
	)
	if st["action_required"]:
		return {"invoice": invoice, "skipped": "over_threshold", "action_required": True}

	now_dt = frappe.utils.get_datetime(now) if now else frappe.utils.now_datetime()
	charge_after = frappe.utils.add_to_date(now_dt, hours=PREDEBIT_NOTICE_HOURS)
	frappe.db.set_value(
		"Invoice", invoice,
		{"predebit_notified_at": now_dt, "predebit_charge_after": charge_after},
		update_modified=False,
	)

	from central.billing.platform import notifications

	notifications.notify(
		inv.team, "Pre-debit Notice",
		context={
			"invoice": invoice,
			"amount": f"{frappe.utils.flt(inv.expected_collection)} {inv.currency or ''}".strip(),
			"charge_on": frappe.utils.format_datetime(charge_after),
		},
		reference_doctype="Invoice", reference_name=invoice,
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
	out = []
	for inv in due:
		if frappe.db.get_value("Billing Profile", inv.team, "collection_mode") != "E-Mandate":
			continue
		out.append({"invoice": inv.name, **collection.collect_invoice(inv.name)})
	return out


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
	notified = [schedule_predebit(name, now=now) for name in pending]
	return {"notified": notified, "charged": charge_due(now=now)}
