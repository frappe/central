import frappe


def execute() -> None:
	"""Copy trial products into the field used to resume product onboarding."""
	for action in frappe.get_all(
		"Resource Action",
		filters={"resource_type": "Site", "action": "create", "product": ["is", "not set"]},
		fields=["name", "team", "request_payload"],
	):
		payload = frappe.parse_json(action.request_payload or "{}")
		product = (payload.get("site") or {}).get("product")
		if product and frappe.db.exists("Product", product):
			frappe.db.set_value("Resource Action", action.name, "product", product, update_modified=False)
