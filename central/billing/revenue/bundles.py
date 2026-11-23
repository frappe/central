# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""What a server's plan includes is its bundle: usage of the same resource above it bills.

A meter records each day what was used and what the plan included that day. A held amount
(GB stored, addresses kept) bills each day above that day's bundle; an amount used up
(transfer) bills the month above the bundle, scaled to the days the plan ran.
"""

import frappe


def included_by_plan(resource_type: str) -> dict[str, float]:
	"""Each plan's included quantity of `resource_type`, for the plans that include any."""
	rows = frappe.get_all(
		"Plan Includes",
		filters={"parenttype": "Plan", "resource_type": resource_type, "quantity": [">", 0]},
		fields=["parent", "quantity"],
	)
	return {row.parent: frappe.utils.flt(row.quantity) for row in rows}
