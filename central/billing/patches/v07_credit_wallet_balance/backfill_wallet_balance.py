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


def execute():
	for team in frappe.get_all("Credit Wallet", pluck="name"):
		balance = frappe.db.sql(
			"""
			SELECT COALESCE(
				SUM(CASE WHEN entry_type = 'credit' THEN amount ELSE -amount END), 0
			)
			FROM `tabCredit Ledger Entry`
			WHERE team = %s
			""",
			team,
		)[0][0]
		frappe.db.set_value(
			"Credit Wallet", team, "balance", frappe.utils.flt(balance), update_modified=False
		)
