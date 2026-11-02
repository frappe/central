import frappe


def execute() -> None:
	"""Remove the Ignored events no record links to. Frappe Cloud v1 sent them over the shared gateway accounts."""
	event = frappe.qb.DocType("Webhook Event")
	(
		frappe.qb.from_(event)
		.delete()
		.where(
			(event.status == "Ignored")
			& (event.payment_attempt.isnull() | (event.payment_attempt == ""))
			& (event.payment_method.isnull() | (event.payment_method == ""))
		)
	).run()
	frappe.db.delete("Billing Event", {"event_type": "Webhook Event Ignored"})
