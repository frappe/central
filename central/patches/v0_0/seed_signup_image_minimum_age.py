import frappe


def execute() -> None:
	if "signup_image_minimum_age_minutes" not in frappe.db.get_singles_dict("Central Settings"):
		frappe.db.set_single_value("Central Settings", "signup_image_minimum_age_minutes", 30)
