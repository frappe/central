# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Composite indexes for the hot billing query shapes.

The single-column indexes ride on the doctypes' `search_index` flags; these are
the multi-column ones a docfield flag can't express:

  - Invoice(status, period_end)      — open_drafts / dunning scan a month's drafts
  - Payment Attempt(invoice, status) — the in-flight check on every charge
  - Usage Rollup(team, cluster, period_start) — per-team rollups at invoice time

Runs after model sync so the tables exist. `add_index` is idempotent (guards on
has_index), so a re-run is a no-op.
"""

import frappe

_INDEXES = (
	("Invoice", ["status", "period_end"]),
	("Payment Attempt", ["invoice", "status"]),
	("Usage Rollup", ["team", "cluster", "period_start"]),
)


def execute():
	for doctype, fields in _INDEXES:
		frappe.db.add_index(doctype, fields)
