import frappe

from central.api.pilot import get_telemetry_base_url, region_id_of
from central.infrastructure.doctype.region.cargo_connection import get_cargo_machine_claims


# nosemgrep: guest-whitelisted-method -- get_cargo_machine_claims verifies the caller below.
@frappe.whitelist(allow_guest=True, methods=["GET"])
def datum_token() -> dict:
	"""The Datum token one Cargo node ships its own metrics and logs with. The node trades
	the machine token Cargo put in its metadata, and fetches again before this one expires.
	Not the Authorization header: Frappe refuses a scheme it cannot map to a user."""
	from central.sso import DATUM_TTL, mint_datum_token

	claims = get_cargo_machine_claims(frappe.get_request_header("X-Cargo-Machine-Token") or "")
	resource_id = f"cargo:{claims['machine']}"

	return {
		"token": mint_datum_token(region_id_of(claims["region"]), resource_id),
		"expires_in": DATUM_TTL,
		"resource_id": resource_id,
		"endpoint": get_telemetry_base_url(claims["region"]),
	}
