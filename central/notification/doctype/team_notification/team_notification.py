# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TeamNotification(Document):
	pass


def on_doctype_update() -> None:
	frappe.db.add_index("Team Notification", ["team", "reference_name", "creation"])
