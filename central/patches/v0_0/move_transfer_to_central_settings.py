import frappe


def execute():
	"""Show one included transfer for every server, and drop the per-plan Transfer rows it replaces.

	A field default applies only when the Single document is first created. Only server plans
	lose the row, so a metered Transfer plan keeps its only resource."""
	if not frappe.db.get_single_value("Central Settings", "included_transfer_gb"):
		frappe.db.set_single_value("Central Settings", "included_transfer_gb", 1024)

	server_categories = frappe.get_all("Plan Category", filters={"provision_target": "Server"}, pluck="name")
	server_plans = frappe.get_all("Plan", filters={"category": ["in", server_categories]}, pluck="name")
	if server_plans:
		frappe.db.delete(
			"Plan Includes",
			{"parenttype": "Plan", "parent": ["in", server_plans], "resource_type": "Transfer"},
		)
