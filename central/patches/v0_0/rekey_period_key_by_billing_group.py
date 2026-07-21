# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Re-key `Invoice.period_key` to include the Billing Group (ADR 0018, I6).

The key was `team|period_start|period_end`, from when a team received exactly one
invoice per period. With Billing-Group partitioning a team receives its consolidated
invoice for ungrouped assets *plus* one per group its assets are tagged into — all
the same team, all the same period. Under the old key those collide, and the unique
index refuses every invoice after the first: the team-alone key does not merely fail
to describe the new grain, it actively blocks it.

This rewrites every live invoice's key to `team|billing_group|period_start|period_end`
(empty group segment = the consolidated invoice). Existing invoices all predate groups,
so they take the empty segment and keep the slot they already held. The rewrite is
injective — same rows, same slots, one more dimension — so it cannot introduce a
collision, and cancelled invoices keep their per-invoice sentinel and are left alone.
"""

import frappe

from central.billing.doctype.invoice.invoice import CANCELLED, period_key_for


def execute():
	invoices = frappe.get_all(
		"Invoice",
		filters={"status": ["!=", CANCELLED]},
		fields=["name", "team", "billing_group", "period_start", "period_end"],
	)

	for inv in invoices:
		key = period_key_for(inv.team, inv.billing_group, inv.period_start, inv.period_end)
		frappe.db.set_value("Invoice", inv.name, "period_key", key, update_modified=False)
