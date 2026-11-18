import frappe
from frappe.query_builder import Table

OLD, NEW = "Email OAuth Provider", "OAuth Provider"


def execute():
	"""Rename `Email OAuth Provider` to `OAuth Provider`, since Meta signs in WhatsApp accounts too.

	`frappe.rename_doc("DocType", ...)` renames the table and every Link to it, but not the
	`__Auth` rows that hold each record's `client_secret`, so those move here. The move runs
	on every call: rename_doc commits the DocType rename before it returns, so a run that
	stopped after it must still move the secrets when it runs again.
	"""
	if frappe.db.exists("DocType", OLD) and not frappe.db.exists("DocType", NEW):
		frappe.rename_doc("DocType", OLD, NEW, force=True, show_alert=False)
	auth = Table("__Auth")
	frappe.qb.update(auth).set(auth.doctype, NEW).where(auth.doctype == OLD).run()
