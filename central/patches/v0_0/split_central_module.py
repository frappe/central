# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Move the identity and infrastructure DocTypes out of the overloaded `Central`
module into the new `Identity` and `Infrastructure` modules.

Frappe finds a standard DocType's JSON from its stored `module`, so the module
column must change before doctype sync runs, or sync looks for the JSON at the
old `central/central/doctype/...` path (now gone) and never learns the new
module. Runs pre_model_sync for that reason, and after the Asset rename above so
`Virtual Machine` already exists.

Only `Central Settings` and `Central SSO Settings` stay in `Central`. Guarded and
idempotent: a DocType already in its target module, or absent, is skipped.
"""

import frappe

MODULE_BY_DOCTYPE = {
	"Identity": (
		"Team",
		"Team Member",
		"Team Invitation",
		"Team Role",
		"Role Capability",
		"Capability",
		"IAM Permission Probe",
	),
	"Infrastructure": (
		"Region",
		"Image Offering",
		"Image Offering Tag",
		"Virtual Machine",
		"Site",
		"Site Domain",
		"Resource Action",
		"Pilot Credential",
	),
}


def execute():
	for module, doctypes in MODULE_BY_DOCTYPE.items():
		for doctype in doctypes:
			if frappe.db.exists("DocType", doctype):
				frappe.db.set_value("DocType", doctype, "module", module, update_modified=False)
