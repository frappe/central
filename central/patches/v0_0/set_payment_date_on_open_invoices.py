import frappe
from frappe.query_builder.functions import Min

from central.billing.doctype.invoice.invoice import owed_filters


def execute() -> None:
	"""Give every open invoice a payment date: the date it opened.

	These invoices were already being collected, so the date never moves later than that.
	The date comes from the invoice's first `Invoice Issued` event, else its creation.
	"""
	invoices = frappe.get_all(
		"Invoice",
		filters=[*owed_filters(), ["payment_date", "is", "not set"]],
		fields=["name", "creation"],
	)
	opened_on = _issued_dates([invoice.name for invoice in invoices])

	for invoice in invoices:
		payment_date = opened_on.get(invoice.name) or invoice.creation
		# An Invoice refuses a manual edit through save, so the date is written directly.
		frappe.db.set_value(
			"Invoice",
			invoice.name,
			"payment_date",
			frappe.utils.getdate(payment_date),
			update_modified=False,
		)


def _issued_dates(invoices: list[str]) -> dict:
	"""The time each invoice was first issued, from its Billing Events."""
	if not invoices:
		return {}

	event = frappe.qb.DocType("Billing Event")
	rows = (
		frappe.qb.from_(event)
		.select(event.subject, Min(event.occurred_at))
		.where(event.subject_doctype == "Invoice")
		.where(event.event_type == "Invoice Issued")
		.where(event.subject.isin(invoices))
		.groupby(event.subject)
		.run()
	)
	return dict(rows)
