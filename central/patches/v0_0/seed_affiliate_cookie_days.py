import frappe


def execute() -> None:
	"""Store the affiliate cookie lifetime on the existing Central Settings, so it does not read as 0."""
	if not frappe.db.get_single_value("Central Settings", "affiliate_cookie_days"):
		frappe.db.set_single_value("Central Settings", "affiliate_cookie_days", 30)
