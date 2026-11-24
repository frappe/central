import frappe

from central.support import enqueue_helpdesk_customer_sync


def execute():
	"""Queue one sync per team, so a slow Helpdesk cannot time out the whole backfill, then give the
	tickets opened before the customer model their team."""
	for team in frappe.get_all("Team", pluck="name"):
		enqueue_helpdesk_customer_sync(team)

	frappe.enqueue("central.support.assign_marked_tickets", queue="long", enqueue_after_commit=True)
