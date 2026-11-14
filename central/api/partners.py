import frappe
from frappe.rate_limiter import rate_limit

from central.identity.doctype.partner_registration.partner_registration import get_registration_by_token


# nosemgrep: guest-whitelisted-method -- the random token from Connect is the key, and the IP rate limit applies.
@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=30, seconds=60, methods="GET")
def get_partner_registration(token: str) -> dict:
	"""The partner registration behind a link from Frappe Connect."""
	return get_registration_by_token(token).get_summary()


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=60, methods="POST")
def complete_partner_registration(token: str, team: str) -> dict:
	"""Make one of the caller's teams the partner's team."""
	return get_registration_by_token(token).complete(team)
