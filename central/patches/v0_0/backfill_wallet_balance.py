# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Backfill the new Credit Wallet `balance` column from the ledger (issue #06
concurrency fix).

The wallet anchor now carries the authoritative running balance, maintained
under its row lock so bookings no longer take a `FOR UPDATE` on the ledger (which
gap-locked the shared `creation` index and deadlocked cross-team bookings). For
every existing wallet, seed `balance` from the signed sum of its team's ledger
entries so the anchor and the ledger agree from the first post-migration booking.
Idempotent: recomputes from the ledger each run.
"""

import frappe
from frappe.query_builder import Case
from frappe.query_builder.functions import Sum


def execute():
	cle = frappe.qb.DocType("Credit Ledger Entry")
	signed = Case().when(cle.entry_type == "Credit", cle.amount).else_(-cle.amount)
	for team in frappe.get_all("Credit Wallet", pluck="name"):
		balance = (
			frappe.qb.from_(cle).select(Sum(signed)).where(cle.team == team).run()
		)[0][0]
		frappe.db.set_value(
			"Credit Wallet", team, "balance", frappe.utils.flt(balance), update_modified=False
		)
