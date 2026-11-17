# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class UsageDay(Document):
	pass


def on_doctype_update() -> None:
	# One row per subject, meter and UTC day: a re-sent line lands on the same row.
	frappe.db.add_unique(
		"Usage Day", ["service", "subject", "meter", "day"], constraint_name="unique_usage_day"
	)
	# The recount reads a subscription's days; the invoice stamps and audits by invoice.
	frappe.db.add_index("Usage Day", ["subscription", "day"])
	frappe.db.add_index("Usage Day", ["invoice"])
	frappe.db.add_index("Usage Day", ["team", "day"])
	frappe.db.add_index("Usage Day", ["landed_at"])
	# The daily estimate, the readiness check and the prune filter on the day alone.
	frappe.db.add_index("Usage Day", ["day", "aggregation"])
