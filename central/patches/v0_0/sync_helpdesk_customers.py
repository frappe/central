import frappe


def execute():
	"""Make every Team a Helpdesk customer and point the tickets opened before the customer model
	at their team. The job reads Helpdesk per team, so it runs after the commit."""
	frappe.enqueue("central.support.backfill_helpdesk_customers", queue="long", enqueue_after_commit=True)
