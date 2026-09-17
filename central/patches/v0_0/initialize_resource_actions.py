import frappe

from central.errors import build_envelope


def execute() -> None:
	"""Preserve historical actions without guessing acceptance or regional VM ownership."""
	# Nullable regional identities stay unset; widening disk precision preserves stored sizes.
	frappe.reload_doc("central", "doctype", "asset")
	frappe.reload_doc("central", "doctype", "resource_action")
	rows = frappe.get_all(
		"Resource Action",
		fields=["name", "title", "resource_id", "owner", "requested_by", "request_key", "status"],
	)
	for row in rows:
		if row.request_key:
			continue

		values = {
			"request_key": f"migrated-{row.name}",
			"title": row.title or row.resource_id or row.name,
			"requested_by": row.requested_by or row.owner,
		}
		if row.status in ("Sent", "In Progress"):
			error = build_envelope("OUTCOME_UNKNOWN")
			values.update(
				status="Uncertain",
				error_code=error["code"],
				error_message=error["message"],
				remediation=error["remediation"],
				retriable=0,
			)
		frappe.db.set_value("Resource Action", row.name, values, update_modified=False)
