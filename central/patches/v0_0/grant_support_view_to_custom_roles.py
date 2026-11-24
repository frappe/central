import frappe
from frappe.utils.fixtures import sync_fixtures


def execute():
	"""Give every team's custom role `support:view`, so its members keep support once support
	needs that capability. Fixtures import after patches, so the capability is loaded first."""
	sync_fixtures("central")
	for name in frappe.get_all("Team Role", filters={"is_system": 0}, pluck="name"):
		role = frappe.get_doc("Team Role", name)
		if any(row.capability == "support:view" for row in role.capabilities):
			continue

		role.append("capabilities", {"capability": "support:view"})
		role.save()
