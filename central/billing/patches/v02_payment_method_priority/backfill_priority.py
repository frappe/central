# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Backfill Payment Method.priority from the existing is_default flag (#28).

Each team's methods become a dense, primary-first order: the current default
takes priority 0, the rest follow by creation. is_default is re-mirrored to
(priority == 0). Idempotent.
"""

import frappe


def execute():
	teams = {t for t in frappe.get_all("Payment Method", pluck="team") if t}
	for team in teams:
		names = frappe.get_all(
			"Payment Method",
			filters={"team": team, "status": ["!=", "cancelled"]},
			order_by="is_default desc, creation asc",
			pluck="name",
		)
		for i, name in enumerate(names):
			frappe.db.set_value(
				"Payment Method",
				name,
				{"priority": i, "is_default": 1 if i == 0 else 0},
				update_modified=False,
			)
