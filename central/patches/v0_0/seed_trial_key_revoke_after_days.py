import frappe


def execute() -> None:
	if "trial_key_revoke_after_days" not in frappe.db.get_singles_dict("AI Settings"):
		frappe.db.set_single_value("AI Settings", "trial_key_revoke_after_days", 30)
