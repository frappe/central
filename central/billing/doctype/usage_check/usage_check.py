# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class UsageCheck(Document):
	pass


def on_doctype_update() -> None:
	# One check per subject, meter, dimension and UTC day: a second sample of a day replaces nothing.
	frappe.db.add_unique(
		"Usage Check",
		["service", "subject", "meter", "dimension", "day"],
		constraint_name="unique_usage_check",
	)
	frappe.db.add_index("Usage Check", ["day", "is_mismatch"])
