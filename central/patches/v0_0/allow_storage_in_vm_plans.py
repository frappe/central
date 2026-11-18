import frappe


def execute() -> None:
	filters = {
		"parenttype": "Plan Category",
		"parent": "VM Plans",
		"parentfield": "allowed_resource_types",
		"resource_type": "Storage",
	}
	if frappe.db.exists("Plan Category Resource Type", filters):
		return

	category = frappe.get_doc("Plan Category", "VM Plans")
	category.append("allowed_resource_types", {"resource_type": "Storage"})
	# A migration runs as the system so it can update the catalog master.
	category.save(ignore_permissions=True)
