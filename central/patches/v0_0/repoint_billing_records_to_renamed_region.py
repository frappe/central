import frappe

RENAMED_REGIONS = {"mumbai": "bom"}


def execute() -> None:
	"""Point billing records at the current name of a renamed region, so their usage can be priced."""
	for old_name, new_name in RENAMED_REGIONS.items():
		if frappe.db.exists("Region", old_name) or not frappe.db.exists("Region", new_name):
			continue
		for doctype in ("Subscription", "Usage Rollup"):
			frappe.db.set_value(doctype, {"cluster": old_name}, "cluster", new_name, update_modified=False)
