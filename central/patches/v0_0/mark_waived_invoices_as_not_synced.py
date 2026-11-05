import frappe


def execute() -> None:
	"""A waived invoice is never sent to the accounting system, so its sync is not pending."""
	frappe.db.set_value(
		"Invoice", {"status": "Waived"}, "erpnext_sync_status", "Not Required", update_modified=False
	)
