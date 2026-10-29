import frappe
from frappe.query_builder.functions import Min


def execute():
	"""Date each Paid invoice that has no `paid_at`, so every reader of a first payment can use it.

	1. The first gateway capture of the invoice dates it, because that is when the money arrived.
	2. Otherwise its last change dates it. This is the closest time Central kept for a settlement by credit."""
	invoice = frappe.qb.DocType("Invoice")
	attempt = frappe.qb.DocType("Payment Attempt")
	undated = (invoice.status == "Paid") & invoice.paid_at.isnull()

	captured = (
		frappe.qb.from_(attempt)
		.select(attempt.invoice, Min(attempt.completed_at).as_("captured_at"))
		.where(attempt.status.isin(["Captured", "Refunded"]))
		.where(attempt.completed_at.isnotnull())
		.groupby(attempt.invoice)
	).as_("captured")
	(
		frappe.qb.update(invoice)
		.join(captured)
		.on(captured.invoice == invoice.name)
		.set(invoice.paid_at, captured.captured_at)
		.where(undated)
	).run()

	frappe.qb.update(invoice).set(invoice.paid_at, invoice.modified).where(undated).run()
