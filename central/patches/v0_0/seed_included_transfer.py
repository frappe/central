import frappe


def execute():
	"""Give an existing site the included transfer its new field defaults to.

	A field default applies only when the Single document is first created."""
	if not frappe.db.get_single_value("Central Settings", "included_transfer_gb"):
		frappe.db.set_single_value("Central Settings", "included_transfer_gb", 1024)
