import frappe


def execute():
	"""Count a day with no derivation only from now: a day stored before services sent evidence is not counted."""
	month = frappe.qb.DocType("Usage Month")
	frappe.qb.update(month).set(month.underived, 0).where(month.underived != 0).run()
