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
from frappe import _

from central.billing import settings
from central.billing.platform.records import save_billing_record
from central.billing.revenue import credits
from central.billing.revenue.invoicing.generate import generate_team_invoice
from central.billing.revenue.tax import is_internal_team
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
	# The run changes only status and amounts; the links were checked when it was drafted.
	doc.flags.ignore_links = True

	# A billable draft waits until it can become a correct statutory invoice. Whatever
	# clears the hold releases it; the monthly run picks up anything a release missed.
	if doc.invoice_type == "Billable":
		if is_internal_team(doc.team):
			return _waive_internal(doc)
		hold = _hold_reason(doc)
		if hold:
			_mark_held(doc, hold)
			return {"invoice": invoice, "claimed": False, "held": HOLD_KEYS[hold]}
		# Re-read now, not at drafting: a GSTIN checked since then changes the tax.
		_retax(doc)

	# Free/trial: a cost_report is computed, never collected — no credits, no
	# charge. It is opened as a record of the subsidy cost.
	if doc.invoice_type == "Cost Report":
		doc.credit_applied = 0
		doc.expected_collection = 0
		transition(doc, "Open", reason="cost report opened", actor="scheduler")
		save_billing_record(doc)
		return {"invoice": invoice, "claimed": True, "cost_report": True, "expected_collection": 0}

	# Leg 1 — credits first (only against the collectable amount, gross less TDS).
	collectable = frappe.utils.flt(doc.total) - frappe.utils.flt(doc.tds_amount)
	draw = (
		_draw_wallet(doc, collectable, frappe.utils.flt(doc.output_tax_amount))
		if collectable > 0
		else frappe._dict(wallet=0, advance=0, gst=0)
	)
	_apply_draw(doc, draw)
	applied = draw.wallet
	# Auto-charge target = gross total, less withheld TDS, less credits and the GST
	# already paid with the top-ups those credits came from.
	doc.expected_collection = frappe.utils.flt(collectable - draw.wallet - draw.gst, 2)
	# Both dates are set from *today*, not from the period end: an invoice the run
	# opened three days late is due three days later, and its dunning ladder starts
	# three days later. A backlog delays collection; it never shortens the customer's
	# window. From here the two diverge — due_date is the accounting fact and stays
	# put, while dunning_starts_on moves if we fail to ask again (dunning.defer_dunning).
	doc.due_date = frappe.utils.add_days(frappe.utils.nowdate(), settings.invoice_due_days())
	doc.dunning_starts_on = doc.due_date

	# Credits cover it in full — settled, no card charge needed.
	if doc.expected_collection <= 0:
		_settle_paid_by_credit(doc, "credits covered in full", applied)
		return {
			"invoice": invoice,
			"claimed": True,
			"credit_applied": applied,
			"expected_collection": 0,
			"status": "Paid",
		}

	transition(doc, "Open", reason="drafted invoice opened for collection", actor="scheduler")
	save_billing_record(doc)

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


def settle_with_new_credit(team: str) -> list[dict]:
	"""Spend credit that landed after invoices were issued on the team's unpaid invoices, oldest first.

	Credit is drawn only at issue, so without this a top-up made to pay an open invoice
	would sit in the wallet while that invoice was dunned, and pay next month's instead."""
	invoices = frappe.get_all(
		"Invoice",
		filters={
			"team": team,
			"invoice_type": "Billable",
			"status": ["in", ["Open", "Overdue"]],
			"expected_collection": [">", 0],
		},
		pluck="name",
		order_by="period_start asc, creation asc",
	)
	return [_settle_with_credit(invoice) for invoice in invoices]


def _settle_with_credit(invoice: str) -> dict:
	"""Pay one unpaid invoice with the wallet, when the wallet covers all of it.

	1. An invoice with a charge in flight is left alone: that charge is for the whole amount.
	   A debit the gateway holds does not stop the credit. It is refunded if it goes through.
	2. Credit that covers only part of the invoice stays in the wallet. It is never split
	   with a charge, so the customer pays the whole amount due in one way.
	"""
	from central.billing.payments import charges

	invoice_tbl = frappe.qb.DocType("Invoice")
	frappe.qb.from_(invoice_tbl).select(invoice_tbl.name).where(
		invoice_tbl.name == invoice
	).for_update().run()
	doc = frappe.get_doc("Invoice", invoice)
	doc.flags.ignore_links = True  # only its amounts and status change here
	due = frappe.utils.flt(doc.expected_collection)
	if (
		doc.status not in ("Open", "Overdue")
		or due <= 0
		or charges.in_flight_attempt(invoice, count_held=False)
	):
		return {"invoice": invoice, "applied": 0}

	draw = _draw_wallet(doc, due, _gst_still_due(doc, due))
	if draw.wallet <= 0 or frappe.utils.flt(due - draw.wallet - draw.gst, 2) > 0:
		return {"invoice": invoice, "applied": 0}

	_apply_draw(doc, draw)
	doc.expected_collection = 0
	_settle_paid_by_credit(doc, "credit added later covered it", draw.wallet)
	return {"invoice": invoice, "applied": draw.wallet, "status": "Paid"}


def _apply_draw(doc, draw: frappe._dict) -> None:
	"""Spend a wallet draw on the invoice and add it to what credit has paid of it."""
	if draw.wallet > 0:
		credits.apply_credit(
			doc.team,
			draw.wallet,
			doc.currency,
			reference_type="Invoice",
			reference_name=doc.name,
			note=f"Credit applied to {doc.name}",
		)
	doc.credit_applied = frappe.utils.flt(doc.credit_applied) + draw.wallet
	doc.advance_applied = frappe.utils.flt(doc.advance_applied) + draw.advance
	doc.advance_tax_applied = frappe.utils.flt(doc.advance_tax_applied) + draw.gst


def _settle_paid_by_credit(doc, reason: str, applied: float) -> None:
	"""Move an invoice that credit paid in full to Paid and queue it for the ERPNext sync."""
	from central.billing.ingester.erpnext_sync import enqueue_invoice_sync

	doc.paid_at = frappe.utils.now_datetime()
	transition(doc, "Paid", reason=reason, actor="scheduler", amount=applied)
	save_billing_record(doc)
	enqueue_invoice_sync(doc.name)


def _gst_still_due(doc, due: float) -> float:
	"""The GST share of what is still due. Earlier credit paid GST in proportion to what it paid."""
	collectable = frappe.utils.flt(doc.total) - frappe.utils.flt(doc.tds_amount)
	if collectable <= 0:
		return 0.0
	return frappe.utils.flt(doc.output_tax_amount) * due / collectable


def _waive_internal(doc) -> dict:
	"""Waive an internal team's invoice in full: rated for the record, never collected."""
	_retax(doc)
	doc.credit_applied = 0
	doc.expected_collection = 0
	transition(doc, "Waived", reason="internal team", actor="scheduler", amount=doc.total)
	save_billing_record(doc)
	return {"invoice": doc.name, "claimed": True, "status": "Waived", "waived": doc.total}


# Hold Reason values, and the keys callers of `open_and_collect` see.
HOLD_KEYS = {
	"Billing Details": "billing_details",
	"Accounting Sync": "accounting_sync",
	"GSTIN Check": "gstin_check",
}


def _draw_wallet(doc, collectable: float, gst_due: float) -> frappe._dict:
	"""What the wallet pays of `collectable`, of which `gst_due` is GST, in the order it is spent.

	Credit with GST already paid on it (a top-up) pays the invoice's net amount, and
	that GST pays the GST on it. Any other credit (promotional, a refund) pays the
	invoice as it stands, GST included. The wallet stays locked until this commits.
	"""
	credits.lock_team_wallet(doc.team, doc.currency)
	net_due = collectable - gst_due
	gst_per_net = gst_due / net_due if gst_due and net_due > 0 else 0
	gst_left = credits.advance_gst_balance(doc.team, doc.currency)

	owed, wallet, advance, gst = collectable, 0.0, 0.0, 0.0
	for lot in credits.credit_lots(doc.team, doc.currency):
		if owed <= 0.005:
			break
		if lot.remaining <= 0:
			continue
		if lot.paid_in and gst_per_net:
			net = min(lot.remaining, owed / (1 + gst_per_net))
			tax = min(net * gst_per_net, max(gst_left - gst, 0))
			wallet, advance, gst, owed = wallet + net, advance + net, gst + tax, owed - net - tax
		else:
			use = min(lot.remaining, owed)
			wallet, owed = wallet + use, owed - use
			if lot.paid_in:
				advance += use
	return frappe._dict(
		wallet=frappe.utils.flt(wallet, 2), advance=frappe.utils.flt(advance, 2), gst=frappe.utils.flt(gst, 2)
	)


def _hold_reason(doc) -> str | None:
	"""Why this billable draft must wait, or None when it may be issued.

	Each check also starts whatever clears it.
	"""
	from central.billing.ingester import customer
	from central.billing.revenue import gst_status

	if _hold_for_billing_details(doc):
		return "Billing Details"
	if customer.awaiting_records(doc.team):
		return "Accounting Sync"
	if gst_status.awaiting_check(doc.team):
		return "GSTIN Check"
	return None


def _mark_held(doc, hold: str) -> None:
	if doc.hold_reason != hold:
		frappe.db.set_value("Invoice", doc.name, "hold_reason", hold, update_modified=False)


def _retax(doc) -> None:
	"""Recompute the draft's tax block from the team's current tax standing."""
	from central.billing.revenue.tax import resolve_tax

	base = frappe.utils.flt(
		frappe.utils.flt(doc.subtotal)
		- frappe.utils.flt(doc.commitment_discount)
		+ frappe.utils.flt(doc.commitment_clawback),
		2,
	)
	doc.update(resolve_tax(doc.team, base))
	doc.total = frappe.utils.flt(base + frappe.utils.flt(doc.output_tax_amount), 2)
	doc.hold_reason = None


def _hold_for_billing_details(doc) -> bool:
	"""Whether this invoice must wait for billing details, asking for them if so.

	The engine dedupes the ask for an hour only, so each retry of the held draft asks
	again. The monthly billing run is the only retry that finds details still missing.
	"""
	from central.billing.doctype.billing_profile.billing_profile import get_missing_field_labels
	from central.billing.platform import notifications

	missing = get_missing_field_labels(doc.team)
	if not missing:
		return False
	notifications.notify(
		doc.team,
		"Billing Details Required",
		message=", ".join(missing),
		reference_doctype="Invoice",
		reference_name=doc.name,
	)
	return True


def held_drafts(team: str | None = None, held_before=None, limit: int | None = None) -> list[dict]:
	"""Billable drafts still waiting to be issued — one team's, or everybody's.

	`held_before` keeps only those whose period closed on or before that date, which
	is how long the invoice has been waiting.
	"""
	filters = [
		["status", "=", "Draft"],
		["invoice_type", "=", "Billable"],
		["period_end", "<=", held_before or frappe.utils.nowdate()],
	]
	if team:
		filters.append(["team", "=", team])
	return frappe.get_all(
		"Invoice",
		filters=filters,
		fields=["name", "team", "total", "currency", "period_end", "hold_reason"],
		order_by="period_end asc",
		limit=limit,
	)


def cancel_invoice(invoice: str, reason: str | None = None) -> str:
	"""Cancel an invoice that is not paid yet (Draft, Open or Overdue).

	Issued line items are never mutated — a correction cancels the whole invoice
	and reissues a fresh one. What the invoice drew from the wallet goes back to it.
	A paid invoice is cancelled with a refund instead.

	The invoice row is locked before the checks, the same row a charge locks to claim
	its attempt, so a charge cannot start between the check and the cancel.
	"""
	doc = frappe.get_doc("Invoice", invoice, for_update=True)
	if doc.status == "Paid":
		frappe.throw(
			_("A paid invoice cannot be cancelled on its own — cancel and refund it instead."),
			frappe.ValidationError,
		)
	if doc.status == "Cancelled":
		return invoice
	if frappe.db.exists(
		"Payment Attempt", {"invoice": invoice, "status": ["in", ["Initiated", "Authorised", "Captured"]]}
	):
		frappe.throw(
			_("A card or UPI payment for this invoice is under way or taken. Settle or refund it first."),
			frappe.ValidationError,
		)
	transition(doc, "Cancelled", reason=reason, actor=frappe.session.user)
	save_billing_record(doc)
	give_back_wallet(doc)
	if reason:
		doc.add_comment("Info", f"Cancelled: {reason}")
	return invoice


def waive_for_internal_team(team: str) -> list[str]:
	"""Waive a team's unpaid invoices once it is internal, and give back what they drew from the wallet.

	An invoice with a card or UPI payment under way or taken is left for an operator."""
	waived = []
	for name in frappe.get_all(
		"Invoice", filters={"team": team, "status": ["in", ["Open", "Overdue"]]}, pluck="name"
	):
		# Collectors claim a payment under this lock, so check for one only once it is held.
		doc = frappe.get_doc("Invoice", name, for_update=True)
		if doc.status not in ("Open", "Overdue") or frappe.db.exists(
			"Payment Attempt", {"invoice": name, "status": ["in", ["Initiated", "Authorised", "Captured"]]}
		):
			continue
		transition(doc, "Waived", reason="team marked internal", actor=frappe.session.user, amount=doc.total)
		save_billing_record(doc)
		give_back_wallet(doc)
		waived.append(name)
	return waived


def settle_internal_teams() -> list[str]:
	"""Waive every internal team's unpaid invoices, so no collection run reaches them."""
	internal = frappe.get_all("Tax Profile", filters={"is_internal": 1}, pluck="team")
	if not internal:
		return []
	teams = frappe.get_all(
		"Invoice",
		filters={"team": ["in", internal], "status": ["in", ["Open", "Overdue"]]},
		pluck="team",
		distinct=True,
	)
	return [name for team in teams for name in _waive_unless_wallet_drifted(team)]


def _waive_unless_wallet_drifted(team: str) -> list[str]:
	"""A wallet short of its ledger refuses the credit back; leave that team to an operator."""
	frappe.db.savepoint("waive_internal_team")
	try:
		return waive_for_internal_team(team)
	except credits.WalletDrift:
		frappe.db.rollback(save_point="waive_internal_team")
		frappe.log_error(title=f"Unpaid invoices of internal team {team} were not waived")
		return []


def give_back_wallet(doc) -> None:
	"""Return what the invoice drew from the wallet, each part as the credit it was."""
	paid_in = frappe.utils.flt(doc.advance_applied)
	promotional = frappe.utils.flt(frappe.utils.flt(doc.credit_applied) - paid_in, 2)
	note = f"Returned from cancelled invoice {doc.name}"
	if paid_in > 0:
		credits.return_credit(
			doc.team,
			paid_in,
			doc.currency,
			"Invoice",
			doc.name,
			note,
			paid_in=True,
			tax_amount=frappe.utils.flt(doc.advance_tax_applied),
		)
	if promotional > 0:
		credits.return_credit(doc.team, promotional, doc.currency, "Invoice", doc.name, note)


def reissue_invoice(invoice: str, reason: str | None = None) -> str | None:
	"""Cancel an invoice and regenerate it from current data for the same period.

	The cancelled invoice is excluded from the draft idempotency check, so a new
	Draft is produced. Returns the new invoice name (or None if nothing to bill).
	"""
	doc = frappe.get_doc("Invoice", invoice)
	cancel_invoice(invoice, reason=reason)
	return generate_team_invoice(doc.team, doc.period_start, doc.period_end)
