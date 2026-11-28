# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class UsageMonth(Document):
	pass


def on_doctype_update() -> None:
	# One row per subject, meter, dimension, month and subscription: a resent line lands on the
	# same row, and a reused bucket name bills each day on the subscription that held it.
	frappe.db.add_unique(
		"Usage Month",
		["service", "subject", "meter", "dimension", "month", "subscription"],
		constraint_name="unique_usage_month",
	)
	# The recount reads a subscription's months; invoicing reads a team's.
	frappe.db.add_index("Usage Month", ["subscription", "resource_type", "dimension", "month"])
	frappe.db.add_index("Usage Month", ["team", "month"])
	frappe.db.add_index("Usage Month", ["team", "stamped_at"])
	frappe.db.add_index("Usage Month", ["resource_id", "resource_type"])
	# The estimate, the readiness check and the hourly recount scan by month and by change.
	frappe.db.add_index("Usage Month", ["service", "month", "aggregation"])
	frappe.db.add_index("Usage Month", ["changed_at"])
	frappe.db.add_index("Usage Month", ["invoice"])
	# The evidence check reads only the rows with a billed day that names no report.
	frappe.db.add_index("Usage Month", ["unreported", "month"])
