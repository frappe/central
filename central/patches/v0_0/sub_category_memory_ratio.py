# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Backfill the memory ratio onto the VM optimisation-profile sub-categories.

The memory ratio (GB RAM per vCPU) the configurator pins moved off a hardcoded
dict and onto the Plan Sub-Category master, so it's configurable. The seed creates
new sub-categories with it; this carries it onto the four VM profiles that already
exist, where they don't yet have one.

Idempotent: only sets the ratio on an existing profile that hasn't got one.
"""

import frappe

VM_RATIOS = {
	"General": "1:4",
	"CPU Optimised": "1:2",
	"Memory Optimised": "1:8",
	"Storage Optimised": "1:8",
}


def execute():
	for name, ratio in VM_RATIOS.items():
		if frappe.db.exists("Plan Sub-Category", name) and not frappe.db.get_value(
			"Plan Sub-Category", name, "memory_ratio"
		):
			frappe.db.set_value("Plan Sub-Category", name, "memory_ratio", ratio, update_modified=False)
