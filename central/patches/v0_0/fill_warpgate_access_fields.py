import frappe
from frappe.utils import now_datetime

DURATIONS = {"1": "1 hour", "3": "3 hours", "6": "6 hours", "12": "12 hours", "24": "1 day"}


def execute() -> None:
	if not frappe.db.has_column("Warpgate Access", "duration_hours"):
		return
	now = now_datetime()
	rows = frappe.db.sql(
		"select name, scope, duration_hours, docstatus, expires_at from `tabWarpgate Access`", as_dict=True
	)
	for row in rows:
		if row.docstatus == 2:
			status = "Revoked"
		elif row.docstatus == 1:
			status = "Active" if row.expires_at and row.expires_at > now else "Expired"
		else:
			status = None
		frappe.db.set_value(
			"Warpgate Access",
			row.name,
			{"access_type": row.scope, "duration": DURATIONS.get(str(row.duration_hours)), "status": status},
			update_modified=False,
		)
