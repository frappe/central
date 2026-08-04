# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Phase 2 (light/parallel) + pre-payment corrections — one invoice at a time.

`open_and_collect` runs the credits-then-card waterfall and claims Draft -> Open
atomically. `cancel_invoice` / `reissue_invoice` are the pre-payment correction
path — issued line items are never mutated; a whole invoice is cancelled and
reissued from current data. Who calls these across a whole period, and on which
worker, is `run.py`'s business.
"""

import frappe

from central.billing import settings
from central.billing.revenue import credits
from central.billing.revenue.invoicing.generate import generate_draft_invoice
from central.billing.states import transition


def open_and_collect(invoice: str, collect: bool = True) -> dict:
	"""Run the credits-then-card waterfall and claim Draft -> Open atomically.

	1. Apply wallet credits first (under the wallet `FOR UPDATE`), reducing the
	   amount due — `credit_applied` recorded on the invoice.
	2. If credits cover the bill in full, the invoice is settled (`Paid`) with no
	   gateway round-trip.
	3. Otherwise open it and charge the **remainder** to the card (#10). A
	   credits-only team with a shortfall is left `Open` for dunning (#14) —
	   never stopped here.

	Concurrency: the invoice row is locked FOR UPDATE and the transition only
	fires from `Draft`, so parallel workers never process the same invoice
	twice — the loser sees a non-Draft status and returns.
	"""
	invoice_tbl = frappe.qb.DocType("Invoice")
	rows = (
		frappe.qb.from_(invoice_tbl)
		.select(invoice_tbl.status)
		.where(invoice_tbl.name == invoice)
		.for_update()
		.run(as_dict=True)
	)
	if not rows or rows[0].status != "Draft":
		return {"invoice": invoice, "claimed": False}

	doc = frappe.get_doc("Invoice", invoice)

	# Free/trial: a cost_report is computed, never collected — no credits, no
	# charge. It is opened as a record of the subsidy cost.
	if doc.invoice_type == "Cost Report":
		doc.credit_applied = 0
		doc.expected_collection = 0
		transition(doc, "Open", reason="cost report opened", actor="scheduler")
		doc.save(ignore_permissions=True)
		return {"invoice": invoice, "claimed": True, "cost_report": True, "expected_collection": 0}

	# Leg 1 — credits first (only against the collectable amount, gross less TDS).
	applied = 0
	collectable = frappe.utils.flt(doc.total) - frappe.utils.flt(doc.tds_amount)
	if collectable > 0:
		# Draw and debit in the invoice's own currency — a USD team's wallet must be
		# debited in USD, not the apply_credit default (INR).
		balance = credits.get_balance(doc.team, doc.currency)["balance"]
		applied = min(frappe.utils.flt(balance), collectable)
		if applied > 0:
			credits.apply_credit(
				doc.team,
				applied,
				doc.currency,
				reference_type="Invoice",
				reference_name=invoice,
				note=f"Credit applied to {invoice}",
			)

	doc.credit_applied = applied
	# Auto-charge target = gross total, less withheld TDS, less credits applied.
	doc.expected_collection = frappe.utils.flt(
		frappe.utils.flt(doc.total) - frappe.utils.flt(doc.tds_amount) - applied, 2
	)
	# Both dates are set from *today*, not from the period end: an invoice the run
	# opened three days late is due three days later, and its dunning ladder starts
	# three days later. A backlog delays collection; it never shortens the customer's
	# window. From here the two diverge — due_date is the accounting fact and stays
	# put, while dunning_starts_on moves if we fail to ask again (dunning.defer_dunning).
	doc.due_date = frappe.utils.add_days(frappe.utils.nowdate(), settings.invoice_due_days())
	doc.dunning_starts_on = doc.due_date

	# Credits cover it in full — settled, no card charge needed.
	if doc.expected_collection <= 0:
		doc.paid_at = frappe.utils.now_datetime()
		transition(doc, "Paid", reason="credits covered in full", actor="scheduler", amount=applied)
		doc.save(ignore_permissions=True)
		return {
			"invoice": invoice,
			"claimed": True,
			"credit_applied": applied,
			"expected_collection": 0,
			"status": "Paid",
		}

	transition(doc, "Open", reason="drafted invoice opened for collection", actor="scheduler")
	doc.save(ignore_permissions=True)

	# Leg 2 — charge the remainder, walking the team's methods primary→backup
	# (#28). Credits-only teams (no active method) fall through to dunning.
	charge = None
	if collect:
		from central.billing.payments import collection

		charge = collection.collect_invoice(invoice)

	return {
		"invoice": invoice,
		"claimed": True,
		"credit_applied": applied,
		"expected_collection": doc.expected_collection,
		"status": "Open",
		"charge": charge,
	}


def cancel_invoice(invoice: str, reason: str | None = None) -> str:
	"""Cancel a pre-payment (Draft/Open/Overdue) invoice.

	Issued line items are never mutated — a correction cancels the whole invoice
	and reissues a fresh one. A Paid invoice cannot be cancelled (use a refund).
	"""
	doc = frappe.get_doc("Invoice", invoice)
	if doc.status == "Paid":
		frappe.throw("A paid invoice cannot be cancelled — issue a refund instead.", frappe.ValidationError)
	if doc.status == "Cancelled":
		return invoice
	transition(doc, "Cancelled", reason=reason, actor=frappe.session.user)
	doc.save(ignore_permissions=True)
	if reason:
		doc.add_comment("Info", f"Cancelled: {reason}")
	return invoice


def reissue_invoice(invoice: str, reason: str | None = None) -> str | None:
	"""Cancel an invoice and regenerate it from current data for the same period.

	The cancelled invoice is excluded from the draft idempotency check, so a new
	Draft is produced. Returns the new invoice name (or None if nothing to bill).
	"""
	doc = frappe.get_doc("Invoice", invoice)
	cancel_invoice(invoice, reason=reason)
	return generate_draft_invoice(doc.subscription, doc.period_start, doc.period_end)
