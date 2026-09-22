from __future__ import annotations

import frappe
from frappe import _

from central.integrations import state_delivery

SOURCE_HEADER = "X-FC-Source"
# Every plane names its region the same way; `X-FC-Source` alone says which plane.
REGION_HEADER = "X-FC-Region"
ATLAS = "atlas"
CARGO = "cargo"


@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive() -> dict:
	"""Take one signed report from a region, from whichever plane sent it.

	Guest route by necessity: the source is a region, not a signed-in user. The shared
	secret is the only gate, and nothing that depends on the body runs before it
	verifies. `X-FC-Source` only picks the handler; each one authenticates the delivery
	itself. The reply says what Central did with the report, so a failed delivery is
	readable in the sender's own log."""
	source = (frappe.get_request_header(SOURCE_HEADER) or "").strip().lower()
	region = frappe.get_request_header(REGION_HEADER)
	signature = frappe.get_request_header("X-Frappe-Webhook-Signature")

	if source == ATLAS:
		return state_delivery.accept_atlas_report(
			raw_body=frappe.request.get_data(),
			region=region,
			signature=signature,
		)

	if source == CARGO:
		return state_delivery.accept_cargo_report(
			raw_body=frappe.request.get_data(),
			region=region,
			signature=signature,
		)

	frappe.throw(_("A delivery must name its source."), frappe.PermissionError)
