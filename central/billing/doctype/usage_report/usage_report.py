# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class UsageReport(Document):
	pass


def on_doctype_update() -> None:
	# The desk list and the retention prune read reports by service and by when they came in.
	frappe.db.add_index("Usage Report", ["service", "received_at"])
	frappe.db.add_index("Usage Report", ["received_at"])
