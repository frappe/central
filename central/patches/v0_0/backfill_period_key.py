# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Backfill `Invoice.period_key` — one live invoice per (team, period) (ADR 0018, I6).

`generate_team_invoice` checked for an existing invoice with `db.get_value` and then
inserted, with no lock and no constraint between the two. `generate_draft_invoices`
enqueues one job *per team*, so a scheduler double-fire or a manual run overlapping the
cron gave two workers that both read "no invoice" and both inserted. The team was billed
twice. A unique index closes the gap; this patch fills the column it indexes.

**Existing duplicates are NOT auto-cancelled.** A duplicate that was already *paid* is
real money, and deciding what to do about it is a human's call, not a patch's. Instead
the canonical invoice for each (team, period) keeps the period_key and the extras get
the cancelled-style sentinel — which lets the unique index be created without silently
destroying evidence — plus a comment naming them for triage. The invariant audit will
keep surfacing them until someone decides.
"""

import frappe

from central.billing.doctype.invoice.invoice import CANCELLED

# Which invoice wins the period slot when duplicates exist: the one furthest through
# the money lifecycle. A Paid invoice always outranks a Draft — never orphan the one
# the customer actually paid.
_RANK = {"Paid": 5, "Overdue": 4, "Open": 3, "Draft": 2, "Waived": 1}


def execute():
	invoices = frappe.get_all(
		"Invoice",
		fields=["name", "team", "period_start", "period_end", "status", "creation"],
		order_by="creation asc",
	)

	groups: dict[tuple, list] = {}
	for inv in invoices:
		if inv.status == CANCELLED:
			_set_key(inv.name, f"{CANCELLED}|{inv.name}")
			continue
		groups.setdefault((inv.team, str(inv.period_start), str(inv.period_end)), []).append(inv)

	for key, rows in groups.items():
		winner = max(rows, key=lambda r: (_RANK.get(r.status, 0), -_seconds(r.creation)))
		_set_key(winner.name, "|".join(key))

		for loser in rows:
			if loser.name == winner.name:
				continue
			# Not cancelled — only stepped out of the unique index, so the row survives
			# for a human to look at. Its status is untouched.
			_set_key(loser.name, f"{CANCELLED}|{loser.name}")
			frappe.get_doc("Invoice", loser.name).add_comment(
				"Comment",
				frappe._(
					"Duplicate bill for {0} {1}–{2}: this team was invoiced more than once "
					"for the period (the pre-ADR-0018 read-then-insert race). {3} is the "
					"invoice of record. This one is left as-is — status unchanged — for "
					"review; if it was paid, it needs a refund, not a cancellation."
				).format(loser.team, loser.period_start, loser.period_end, winner.name),
			)
			frappe.logger("billing").warning(
				f"duplicate invoice {loser.name} for ({loser.team}, {loser.period_start}); "
				f"invoice of record is {winner.name}"
			)


def _seconds(creation) -> float:
	return frappe.utils.get_datetime(creation).timestamp()


def _set_key(invoice: str, key: str):
	frappe.db.set_value("Invoice", invoice, "period_key", key, update_modified=False)
