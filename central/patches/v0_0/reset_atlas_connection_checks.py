import frappe


def execute() -> None:
	"""Discard reachability results that did not verify the regional token contract."""
	region = frappe.qb.DocType("Region")
	frappe.qb.update(region).set(region.reachable, 0).where(region.connection_checked_at.isnull()).run()
