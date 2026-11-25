import frappe
from frappe.utils.password import set_encrypted_password

SETTINGS = "Billing Settings"


def execute():
	"""Copy the accounting connection from the site config into Billing Settings, with the sync Off.

	An operator picks Manual or Automatic. The site config keys are read no more and can be removed.
	"""
	frappe.db.set_single_value(SETTINGS, "accounting_sync_mode", "Off")
	for field, key in (("accounting_url", "erpnext_url"), ("accounting_api_key", "erpnext_api_key")):
		if frappe.conf.get(key) and not frappe.db.get_single_value(SETTINGS, field):
			frappe.db.set_single_value(SETTINGS, field, frappe.conf.get(key))

	secret = frappe.conf.get("erpnext_api_secret")
	if secret and not frappe.get_single(SETTINGS).get_password(
		"accounting_api_secret", raise_exception=False
	):
		set_encrypted_password(SETTINGS, SETTINGS, secret, "accounting_api_secret")
