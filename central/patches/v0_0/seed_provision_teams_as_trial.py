# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Carry the `central_trial_provisioning` site-config flag onto Billing Settings.

Whether new teams are created as staging trials used to be a bench conf flag; it
is a Billing Settings knob now. This flips the Single on for a staging bench that
already had the conf set, so team bootstrap keeps behaving the day of the deploy.
A one-time patch, not a migrate hook, so turning it off later isn't undone.
"""

import frappe


def execute():
	value = frappe.conf.get("central_trial_provisioning")
	if not value:
		return
	frappe.db.set_single_value("Billing Settings", "provision_teams_as_trial", value)
