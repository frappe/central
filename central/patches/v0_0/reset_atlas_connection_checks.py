import frappe


def execute() -> None:
	"""Discard reachability results that did not verify the regional token contract."""
	instance = frappe.qb.DocType("Atlas Instance")
	frappe.qb.update(instance).set(instance.reachable, 0).where(instance.connection_checked_at.isnull()).run()
