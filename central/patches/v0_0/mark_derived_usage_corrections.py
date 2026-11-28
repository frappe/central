import frappe


def execute():
	"""Mark every kept correction derived, as the days are; current code sets the check on write."""
	# Only rows an earlier rung's code wrote change (dev, test sites, staged deploys).
	correction = frappe.qb.DocType("Usage Month Correction")
	frappe.qb.update(correction).set(correction.derived, 1).where(correction.derived == 0).run()
