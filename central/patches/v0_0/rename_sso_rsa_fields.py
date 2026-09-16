import frappe
from frappe import _
from frappe.model.utils.rename_field import rename_field

DOCTYPE = "Central SSO Settings"
FIELD_RENAMES = {
	"kid": "rsa_key_id",
	"public_key": "rsa_public_key",
	"private_key": "rsa_private_key",
}


def execute() -> None:
	"""Preserve the RSA signing identity, including its encrypted Password field."""
	values = frappe.db.get_singles_dict(DOCTYPE, for_update=True)
	password_fields = frappe.qb.get_query(
		"__Auth",
		filters={"doctype": DOCTYPE, "name": DOCTYPE, "encrypted": 1},
		fields=["fieldname"],
	).run(pluck=True)
	present = {field for field, value in values.items() if value} | set(password_fields)
	if not present.intersection(FIELD_RENAMES):
		return

	if present.intersection(FIELD_RENAMES.values()):
		frappe.throw(
			_("Both RSA signing field sets contain data. Resolve the signing identity before migration.")
		)

	for old_field, new_field in FIELD_RENAMES.items():
		# Remove empty destination rows before the Framework moves the saved Single value.
		frappe.db.delete("Singles", {"doctype": DOCTYPE, "field": new_field})
		rename_field(DOCTYPE, old_field, new_field)

	frappe.clear_document_cache(DOCTYPE, DOCTYPE)
