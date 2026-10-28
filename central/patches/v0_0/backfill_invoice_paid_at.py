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
		frappe.qb.from_(invoice)
		.join(attempt)
		.on(attempt.invoice == invoice.name)
		.select(invoice.name, Min(attempt.completed_at).as_("captured_at"))
		.where(undated)
		.where(attempt.status.isin(["Captured", "Refunded"]))
		.where(attempt.completed_at.isnotnull())
		.groupby(invoice.name)
	).run(as_dict=True)
	for row in captured:
		frappe.db.set_value("Invoice", row.name, "paid_at", row.captured_at, update_modified=False)

	frappe.qb.update(invoice).set(invoice.paid_at, invoice.modified).where(undated).run()
