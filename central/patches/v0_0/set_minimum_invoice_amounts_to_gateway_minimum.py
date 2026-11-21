import frappe

from central.billing.settings import GATEWAY_MINIMUM_CHARGES


def execute() -> None:
	"""Lower each minimum invoice amount to the smallest charge the gateways accept.

	The old default of INR 50 wrote off months that a gateway can charge."""
	for currency, limit in GATEWAY_MINIMUM_CHARGES.items():
		frappe.db.set_value(
			"Minimum Invoice Amount",
			{"parent": "Billing Settings", "currency": currency, "amount": [">", limit]},
			"amount",
			limit,
		)
	frappe.clear_document_cache("Billing Settings", "Billing Settings")
