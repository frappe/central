import frappe


def execute():
	frappe.db.set_value("Notification Event Type", {"category": "Server"}, "reportable_by", "Pilot")
