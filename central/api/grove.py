"""What Grove, the AI gateway's control plane, asks Central for. Grove calls as itself, not as a
user: an `X-Grove-Token` whose SHA-256 AI Settings holds (Grove Token Hash), the mirror of the
Grove key Central keeps there."""

import functools
import hashlib
import hmac
from collections.abc import Callable

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from central.sso import DATUM_TTL, mint_datum_token

TOKEN_HEADER = "X-Grove-Token"
RESOURCE_PREFIX = "grove:"


def grove_token_auth(func: Callable) -> Callable:
	"""Authenticate Grove by its X-Grove-Token against the hash AI Settings holds: 401 on a missing
	or wrong token, and on a blank hash, which admits nobody. Sits under
	@frappe.whitelist(allow_guest=True), a custom header because Frappe claims Authorization before
	a guest endpoint runs."""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		expected = frappe.db.get_single_value("AI Settings", "grove_token_hash") or ""
		presented = hashlib.sha256((frappe.get_request_header(TOKEN_HEADER) or "").encode()).hexdigest()
		if not expected or not hmac.compare_digest(presented, expected):
			frappe.throw(_("Invalid Grove token."), frappe.AuthenticationError)
		return func(*args, **kwargs)

	return wrapper


# nosemgrep: guest-whitelisted-method -- grove_token_auth verifies the caller below, and the IP rate limit applies.
@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=30, seconds=60, methods="GET")
@grove_token_auth
def datum_token(region: str, resource_id: str) -> dict:
	"""The JWT one Grove box presents to its region's datum, for metrics and logs alike. The same
	claims as a Pilot's; Grove names the machine `grove:<machine>`, a namespace of its own so it can
	never write as one of Central's servers. Grove mints it inside the job that writes it to the
	box and asks again with a day of its life left."""
	if not resource_id.startswith(RESOURCE_PREFIX):
		frappe.throw(_("A Grove resource id starts with {0}.").format(RESOURCE_PREFIX), frappe.ValidationError)

	region_id = frappe.get_doc("Region", region).get_atlas_region_id()

	return {"token": mint_datum_token(region_id, resource_id), "expires_in": DATUM_TTL}
