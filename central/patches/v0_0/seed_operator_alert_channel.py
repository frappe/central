import frappe


def execute():
	"""Send billing operator alerts to Raven on a site that already had Billing Settings.

	A field default applies only when the Single document is first created, so an existing
	site would read the alert channel as empty."""
	if not frappe.db.get_single_value("Billing Settings", "operator_alert_channel"):
		frappe.db.set_single_value("Billing Settings", "operator_alert_channel", "Raven")
