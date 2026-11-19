import frappe


def execute():
	"""Point billing at the default rate API on a site that already had Billing Settings."""
	# A field default applies only when the Single is first created.
	if not frappe.db.get_single_value("Billing Settings", "exchange_rate_url"):
		frappe.db.set_single_value("Billing Settings", "exchange_rate_url", "https://api.frankfurter.dev/v2")
