import frappe

SETTINGS = "Billing Settings"


def execute():
	"""Give every currency row of Billing Settings the advance and income account the settings had for all.

	An operator then sets the account of each other currency, such as a USD advance account."""
	singles = frappe.qb.DocType("Singles")
	old = dict(
		frappe.qb.from_(singles)
		.select(singles.field, singles.value)
		.where((singles.doctype == SETTINGS) & singles.field.isin(("advance_account", "income_account")))
		.run()
	)
	for row in frappe.get_all("Accounting Receivable Account", filters={"parent": SETTINGS}, fields=["*"]):
		values = {
			field: old.get(field) for field in ("advance_account", "income_account") if not row.get(field)
		}
		if any(values.values()):
			frappe.db.set_value("Accounting Receivable Account", row.name, values, update_modified=False)
	frappe.db.delete("Singles", {"doctype": SETTINGS, "field": ("in", ("advance_account", "income_account"))})
	frappe.clear_document_cache(SETTINGS, SETTINGS)
