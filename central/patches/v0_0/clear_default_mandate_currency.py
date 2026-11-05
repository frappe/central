import frappe
from frappe.query_builder.functions import IfNull


def execute():
	"""Clear the mandate currency a card without a mandate got from the old INR default.

	Razorpay methods are always mandates and set their currency on purpose, so they keep it."""
	method = frappe.qb.DocType("Payment Method")
	gateway = frappe.qb.DocType("Payment Gateway")
	razorpay = frappe.qb.from_(gateway).select(gateway.name).where(gateway.adapter_key == "Razorpay")
	(
		frappe.qb.update(method)
		.set(method.mandate_currency, None)
		.where(method.mandate_currency.isnotnull())
		.where(IfNull(method.mandate_max_amount, 0) == 0)
		.where(method.gateway.notin(razorpay))
	).run()
