import frappe

DEFAULTS = {
	"alias_email_domains": "erpnext.com\nfrappe.io",
	"refuse_temporary_emails": 1,
	"signup_requests_per_minute": 10,
	"automatic_block_hours": 24,
}


def execute() -> None:
	"""Give the new signup checks their defaults on a site that had none of them yet."""
	if frappe.db.get_single_value("Central Settings", "automatic_block_hours"):
		return

	for fieldname, value in DEFAULTS.items():
		frappe.db.set_single_value("Central Settings", fieldname, value)
