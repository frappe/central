import frappe

RENAMES = (
	("pilot", "title", "Pilot", "Frappe"),
	("pilot", "description", "Pilot with a Frappe bench.", "A Frappe bench, ready for your apps."),
	("ubuntu", "description", "A plain Ubuntu server without Pilot.", "A plain Ubuntu server."),
)


def execute() -> None:
	"""Customers pick Frappe, not Pilot. Only a value an operator has not changed is replaced."""
	for name, field, old, new in RENAMES:
		frappe.db.set_value("Image Offering", {"name": name, field: old}, field, new)
