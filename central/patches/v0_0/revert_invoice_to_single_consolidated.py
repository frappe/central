# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Undo the Billing-Group invoice partitioning: a team bills on ONE consolidated
invoice per period again, never one per project (breaking change, requested
directly). `period_key` drops back to `team|period_start|period_end`; the
project-wise view moves onto the invoice's own line items instead (a new
`project` field on Invoice Line Item, added directly in its JSON — a plain new
column needs no migration of its own).

Runs post_model_sync, after `invoice.json` has already dropped the
`billing_group` field (the column itself is dropped here, once nothing still
needs it).

A team that was actually billed on more than one live invoice for the same
period (a real group-partitioned bill from before this reverts) can no longer
all collapse onto one `period_key` slot — the unique index would refuse every
row after the first. Keep the newest live invoice for that (team, period) as
the team's one bill; anything older with the same period is cancelled rather
than left fighting over a slot it can no longer hold, since a bill this old-and-
superseded is not one anyone still expects to collect from directly.
"""

import frappe

CANCELLED = "Cancelled"


def execute():
	if not frappe.db.has_column("Invoice", "billing_group"):
		return

	live = frappe.get_all(
		"Invoice",
		filters={"status": ["!=", CANCELLED]},
		fields=["name", "team", "period_start", "period_end", "creation"],
		order_by="creation desc",
	)
	seen = set()
	for inv in live:
		key = (inv.team, str(inv.period_start), str(inv.period_end))
		if key in seen:
			# A second live invoice for a period already claimed by a newer row —
			# leftover from group partitioning. Cancel it rather than let it
			# contend for a period_key slot on a model that no longer has one.
			frappe.db.set_value(
				"Invoice", inv.name, "period_key", f"{CANCELLED}|{inv.name}", update_modified=False
			)
			frappe.db.set_value("Invoice", inv.name, "status", CANCELLED, update_modified=False)
			continue
		seen.add(key)
		frappe.db.set_value(
			"Invoice",
			inv.name,
			"period_key",
			f"{inv.team}|{inv.period_start}|{inv.period_end}",
			update_modified=False,
		)

	frappe.db.sql_ddl("ALTER TABLE `tabInvoice` DROP COLUMN `billing_group`")
