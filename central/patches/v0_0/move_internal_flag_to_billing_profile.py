import frappe


def execute() -> None:
	"""Copy the internal flag from Tax Profile, whose old columns stay until a schema cleanup.

	An internal team without a Billing Profile gets a bare one, so its invoices stay waived."""
	if not frappe.db.has_column("Tax Profile", "is_internal"):
		return
	for row in internal_tax_profiles():
		reason = row.internal_reason or "Marked internal on the Tax Profile"
		if not frappe.db.exists("Billing Profile", row.team):
			_insert_bare_profile(row.team)
		frappe.db.set_value(
			"Billing Profile", row.team, {"is_internal": 1, "internal_reason": reason}, update_modified=False
		)


def internal_tax_profiles() -> list[frappe._dict]:
	"""Teams marked internal in the old Tax Profile columns."""
	tax = frappe.qb.DocType("Tax Profile")
	return (
		frappe.qb.from_(tax)
		.select(tax.team, tax.internal_reason)
		.where(tax.is_internal == 1)
		.run(as_dict=True)
	)


def _insert_bare_profile(team: str) -> None:
	doc = frappe.get_doc({"doctype": "Billing Profile", "team": team, "currency": "INR"})
	doc.flags.ignore_validate = True
	doc.flags.ignore_links = True
	doc.flags.ignore_mandatory = True
	doc.db_insert()
