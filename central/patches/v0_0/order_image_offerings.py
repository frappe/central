import frappe


def execute() -> None:
	"""Show Frappe first, then Apps, then Ubuntu. An offering an operator already ordered keeps its place."""
	for order, name in enumerate(("pilot", "apps", "ubuntu"), start=1):
		frappe.db.set_value("Image Offering", {"name": name, "display_order": 0}, "display_order", order)
