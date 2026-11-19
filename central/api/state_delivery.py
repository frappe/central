import frappe
from frappe import _

from central.integrations import state_delivery

SOURCE_HEADER = "X-FC-Source"
# Every plane names its region the same way; `X-FC-Source` alone says which plane.
REGION_HEADER = "X-FC-Region"
ATLAS = "atlas"
CARGO = "cargo"


# nosemgrep: guest-whitelisted-method -- each handler verifies the region's signature before it reads the body.
@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive() -> dict:
	"""Take one signed state report from a region.
	Guest by necessity: the shared secret is the only gate, and nothing reads the body before
	it verifies. `X-FC-Source` only selects the handler, which authenticates the delivery."""
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
