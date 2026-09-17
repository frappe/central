from __future__ import annotations

import frappe

from central.integrations import state_delivery


@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive() -> dict:
	"""Take one signed state report from a region.

	Guest route by necessity: the sender is a region, not a signed-in user. The shared
	secret is the only gate, and nothing that depends on the body runs before it
	verifies. The reply says what Central did with the report, so a failed delivery is
	readable in the sender's own log."""
	return state_delivery.accept(
		raw_body=frappe.request.get_data(),
		region=frappe.get_request_header("X-Atlas-Region"),
		signature=frappe.get_request_header("X-Frappe-Webhook-Signature"),
	)
