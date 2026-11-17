import frappe


def execute() -> None:
	"""The Growth trust tier becomes Emerging. This runs before the fixture sync, which would
	otherwise add Emerging next to Growth."""
	if not frappe.db.exists("Trust Tier Level", "Growth"):
		return

	frappe.rename_doc("Trust Tier Level", "Growth", "Emerging", force=True)

	# Saving the new label also renames the Tier at Grove, through the level's update hook.
	level = frappe.get_doc("Trust Tier Level", "Emerging")
	level.tier = "Emerging"
	level.save()

	frappe.db.set_value("Billing Profile", {"trust_tier": "Growth"}, "trust_tier", "Emerging")
