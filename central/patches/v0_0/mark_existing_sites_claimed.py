import frappe


def execute():
	"""Keep existing sites out of the first-run onboarding funnel."""
	frappe.db.set_value(
		"Site",
		{"claimed_at": ["is", "not set"]},
		"claimed_at",
		frappe.utils.now_datetime(),
		update_modified=False,
	)
