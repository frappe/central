# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Phase 2 (1st, light/parallel) + pre-payment corrections.

`open_and_collect` runs the credits-then-card waterfall and claims Draft -> Open
atomically. `cancel_invoice` / `reissue_invoice` are the pre-payment correction
path — issued line items are never mutated; a whole invoice is cancelled and
reissued from current data.
"""

import frappe

from central.billing.revenue import credits
from central.billing.revenue.invoicing.generate import generate_draft_invoice, generate_draft_invoices

DEFAULT_DUE_DAYS = 7


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
		doc.status = "Open"
		doc.save(ignore_permissions=True)
		return {"invoice": invoice, "claimed": True, "cost_report": True, "expected_collection": 0}

	# Leg 1 — credits first (only against the collectable amount, gross less TDS).
	applied = 0
	collectable = frappe.utils.flt(doc.total) - frappe.utils.flt(doc.tds_amount)
	if collectable > 0:
		balance = credits.get_balance(doc.team)["balance"]
		applied = min(frappe.utils.flt(balance), collectable)
		if applied > 0:
			credits.apply_credit(
				doc.team, applied, reference_type="Invoice", reference_name=invoice,
				note=f"Credit applied to {invoice}",
			)

	doc.credit_applied = applied
	# Auto-charge target = gross total, less withheld TDS, less credits applied.
	doc.expected_collection = frappe.utils.flt(
		frappe.utils.flt(doc.total) - frappe.utils.flt(doc.tds_amount) - applied, 2
	)
	doc.due_date = frappe.utils.add_days(frappe.utils.nowdate(), DEFAULT_DUE_DAYS)

	# Credits cover it in full — settled, no card charge needed.
	if doc.expected_collection <= 0:
		doc.status = "Paid"
		doc.save(ignore_permissions=True)
		return {"invoice": invoice, "claimed": True, "credit_applied": applied,
				"expected_collection": 0, "status": "Paid"}

	doc.status = "Open"
	doc.save(ignore_permissions=True)

	# Leg 2 — charge the remainder, walking the team's methods primary→backup
	# (#28). Credits-only teams (no active method) fall through to dunning.
	charge = None
	if collect:
		from central.billing.payments import collection

		charge = collection.collect_invoice(invoice)

	return {"invoice": invoice, "claimed": True, "credit_applied": applied,
			"expected_collection": doc.expected_collection, "status": "Open", "charge": charge}


def open_drafts(period_end, enqueue: bool = False) -> list[str]:
	"""Phase-2 orchestrator: open every Draft for the billing month."""
	drafts = frappe.get_all(
		"Invoice", filters={"status": "Draft", "period_end": period_end}, pluck="name"
	)
	for inv in drafts:
		if enqueue:
			frappe.enqueue("central.billing.revenue.invoicing.open_and_collect", invoice=inv)
		else:
			open_and_collect(inv)
	return drafts


def run_monthly_billing(today=None) -> dict:
	"""Scheduled entrypoint (1st of the month): bill the just-closed calendar month
	end-to-end for every team — the production trigger for the two-phase invoicing
	(#09/#10) that otherwise only ran from demos and tests.

	Phase 1 drafts one consolidated invoice per team for the previous month; phase 2
	opens each Draft and runs the credits-then-card waterfall — settling it, or leaving
	it Open for dunning (#14). Idempotent: drafting is idempotent per (team, period) and
	open_drafts only touches invoices still in Draft, so a retried tick is safe.
	"""
	today = frappe.utils.getdate(today or frappe.utils.nowdate())
	period_start = frappe.utils.get_first_day(today, d_months=-1)
	period_end = frappe.utils.get_last_day(period_start)

	drafted = generate_draft_invoices(period_start, period_end)
	opened = open_drafts(period_end)
	return {
		"period_start": str(period_start),
		"period_end": str(period_end),
		"drafted": len(drafted),
		"opened": len(opened),
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
	doc.status = "Cancelled"
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
