import frappe


def execute():
	"""Deploys used a Growth VM by default before the size moved to Central Settings."""
	if not frappe.db.get_single_value("Central Settings", "deploy_default_size"):
		frappe.db.set_single_value("Central Settings", "deploy_default_size", "Growth")
