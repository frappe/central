# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Carry the `trial_plans` site-config allow-list onto Plan.available_on_trial.

The trial allow-list used to be a JSON list in site config; it is a per-Plan
check now. This flags the plans a migrated site already offered on trial, so the
menu it shows staging-trial teams is unchanged the day of the deploy. A one-time
patch, not a migrate hook, so un-flagging a plan later is not undone next deploy.
"""

import frappe


def execute():
	value = frappe.conf.get("trial_plans")
	if not value:
		return
	names = frappe.parse_json(value) if isinstance(value, str) else value
	for name in {str(x).strip() for x in (names or []) if str(x).strip()}:
		if frappe.db.exists("Plan", name):
			frappe.db.set_value("Plan", name, "available_on_trial", 1)
