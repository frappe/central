import frappe


def execute() -> None:
	"""A Pilot build may have no site, so the default description no longer claims one."""
	frappe.db.set_value(
		"Image Offering",
		{"name": "pilot", "description": "Pilot with a Frappe bench and one prepared site."},
		"description",
		"Pilot with a Frappe bench.",
	)
