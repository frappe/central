import frappe


def execute() -> None:
	if not frappe.db.exists("DocType", "Host Access Grant"):
		return
	frappe.rename_doc("DocType", "Host Access Grant", "Warpgate Access", force=True, show_alert=False)
