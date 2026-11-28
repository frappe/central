import frappe


def execute():
	"""Keep usage as one row per subject and month: fold every Usage Day and recounted rollup into it."""
	# Imported here, so the patch still loads after the fold module is removed.
	from central.billing.revenue.usage_fold import fold_all

	if not frappe.db.table_exists("Usage Day"):
		return
	fold_all()
