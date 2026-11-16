import frappe


def execute() -> None:
	"""Give the Viewer role to each Partner Link made before links had a role. Viewer is the
	role a new link starts with."""
	link = frappe.qb.DocType("Partner Link")
	frappe.qb.update(link).set(link.role, "Viewer").where(link.role.isnull() | (link.role == "")).run()
