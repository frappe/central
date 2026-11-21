import frappe

from central.errors import build_envelope


def execute() -> None:
	"""Clear the catalog copy that a Resource Action stored in English, so each reader
	gets it in their own language. Copy that the region gave stays."""
	actions = frappe.get_all(
		"Resource Action",
		filters={"error_code": ("is", "set")},
		fields=["name", "error_code", "action", "resource_id", "error_message", "remediation"],
	)
	for action in actions:
		catalog = build_envelope(action.error_code, action=action.action, resource_id=action.resource_id)
		values = {}
		if action.error_message == catalog["message"]:
			values["error_message"] = None
		if action.remediation == catalog["remediation"]:
			values["remediation"] = None
		if values:
			frappe.db.set_value("Resource Action", action.name, values, update_modified=False)
