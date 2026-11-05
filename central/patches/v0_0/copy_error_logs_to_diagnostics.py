import frappe
from frappe.query_builder import Field

# The doctype, its old Error Log link column and the field that now holds the diagnostic.
LINKS = (
	("Resource Action", "error_log", "diagnostic"),
	("Site", "rename_error_log", "rename_diagnostic"),
	("Site Domain", "error_log", "diagnostic"),
	("Virtual Machine", "admin_domain_error_log", "admin_domain_diagnostic"),
	("VM Snapshot", "error_log", "diagnostic"),
)


def execute() -> None:
	"""Copy each linked Error Log onto its record, because Frappe clears Error Logs after their retention period."""
	for doctype, link, field in LINKS:
		if not frappe.db.has_column(doctype, link):
			continue

		table = frappe.qb.DocType(doctype)
		rows = (
			frappe.qb.from_(table)
			.select(table.name, Field(link).as_("error_log"))
			.where(Field(link).isnotnull() & (Field(link) != ""))
			.run(as_dict=True)
		)
		for row in rows:
			if diagnostic := get_error_log_text(row.error_log):
				frappe.db.set_value(doctype, row.name, field, diagnostic, update_modified=False)


def get_error_log_text(name: str) -> str | None:
	try:
		error_log = frappe.get_doc("Error Log", name)
	except frappe.DoesNotExistError:
		return None

	return f"{error_log.method}\n\n{error_log.error}"
