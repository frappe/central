# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class UsageRollup(Document):
	pass


def on_doctype_update() -> None:
	# Invoicing reads a team's rollups for its clusters and the month.
	frappe.db.add_index("Usage Rollup", ["team", "cluster", "period_start"])
