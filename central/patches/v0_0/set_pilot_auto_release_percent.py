import frappe


def execute():
	"""Existing sites get the field's default, so a rollout releases to everyone at 95%."""
	frappe.db.set_single_value("Central Settings", "pilot_auto_release_percent", 95)
