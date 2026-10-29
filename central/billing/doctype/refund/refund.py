# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Refund(Document):
	pass


def on_doctype_update() -> None:
	# The billing run, its dashboards and the money reports filter on these.
	frappe.db.add_index("Refund", ["invoice"])
	frappe.db.add_index("Refund", ["status", "created_at"])
	# Reconciliation rechecks recently completed refunds.
	frappe.db.add_index("Refund", ["status", "completed_at"])
