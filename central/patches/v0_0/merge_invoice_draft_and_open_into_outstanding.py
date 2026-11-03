import frappe
from frappe.utils import add_days, getdate

from central.billing import settings


def execute() -> None:
	"""An invoice is Outstanding from creation; a due date now marks that collection began.

	An Open invoice with no due date gets one first, or the next sweep would collect it twice."""
	days = settings.invoice_due_days()
	for invoice in frappe.get_all(
		"Invoice", filters={"status": "Open", "due_date": ["is", "not set"]}, fields=["name", "modified"]
	):
		frappe.db.set_value(
			"Invoice",
			invoice.name,
			"due_date",
			add_days(getdate(invoice.modified), days),
			update_modified=False,
		)
	frappe.db.set_value("Invoice", {"status": "Draft"}, "due_date", None, update_modified=False)
	for old_status in ("Draft", "Open"):
		frappe.db.set_value("Invoice", {"status": old_status}, "status", "Outstanding", update_modified=False)
