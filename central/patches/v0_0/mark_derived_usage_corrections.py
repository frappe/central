import frappe


def execute():
	"""Mark the corrections set by a segment or a migrated report as derived. Others stay not derived."""
	correction = frappe.qb.DocType("Usage Month Correction")
	report = frappe.qb.DocType("Usage Report")
	migrated = frappe.qb.from_(report).select(report.name).where(report.kind == "Migrated")
	(
		frappe.qb.update(correction)
		.set(correction.derived, 1)
		.where(
			(correction.segment.isnotnull() & (correction.segment != "")) | correction.report.isin(migrated)
		)
	).run()
