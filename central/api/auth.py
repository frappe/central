from __future__ import annotations

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import validate_email_address

from central.identity.doctype.team_invitation.team_invitation import get_invitation_by_token
from central.identity.email_code import EmailCode
from central.users import create_user, send_sign_in_code, sign_in_with_code
from central.utils.inputs import require_text

FULL_NAME_MAX_LENGTH = 140


# nosemgrep: guest-whitelisted-method -- sending is limited by IP and by email.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=EmailCode.TTL_SECONDS, methods="POST")
@rate_limit(
	key="email",
	ip_based=False,
	endpoint="central.auth.code_send",
	limit=5,
	seconds=EmailCode.TTL_SECONDS,
	methods="POST",
)
def send_code(email: str, full_name: str | None = None, product: str | None = None) -> dict:
	"""Email a sign-in code. A new email gets a code too, and the account is made on verify."""
	email = _validated_email(email)
	send_sign_in_code(email, _optional_full_name(full_name), _known_product(product))
	return {"message": _("We sent a code to {0}.").format(email)}


# nosemgrep: guest-whitelisted-method -- a short-lived code and an attempt limit authenticate the user.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=EmailCode.TTL_SECONDS, methods="POST")
@rate_limit(
	key="email",
	ip_based=False,
	endpoint="central.auth.code_verify",
	limit=10,
	seconds=EmailCode.TTL_SECONDS,
	methods="POST",
)
def verify_code(email: str, code: str, full_name: str | None = None, product: str | None = None) -> dict:
	"""Sign in with an emailed code. Returns `needs_name` when a new account has no name yet."""
	email = _validated_email(email)
	if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
		frappe.throw(_("Enter the 6-digit code from your email."), frappe.ValidationError)

	return sign_in_with_code(email, code, _optional_full_name(full_name), _known_product(product))


# nosemgrep: guest-whitelisted-method -- the emailed token verifies the address, and the IP rate limit applies.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=EmailCode.TTL_SECONDS, methods="POST")
def sign_up_with_invitation(token: str, full_name: str) -> dict:
	"""Create the invited user's account and join the team.

	The emailed token verifies the address. An existing account must sign in instead."""
	full_name = _required_full_name(full_name)
	invitation = get_invitation_by_token(token)
	if not invitation.is_pending:
		frappe.throw(_("This invitation is no longer valid."), frappe.ValidationError)
	if frappe.db.exists("User", invitation.email):
		frappe.throw(
			_("An account with this email already exists. Sign in to accept."), frappe.ValidationError
		)

	user = create_user(invitation.email, full_name)
	frappe.local.login_manager.login_as(user.name)
	# Only this invitation: the others for the email stay pending for the user to answer.
	invitation.accept()
	return {"user": user.name, "team": invitation.team}


def _validated_email(email: str) -> str:
	if not isinstance(email, str) or len(email) > 254:
		frappe.throw(_("Enter a valid email address."), frappe.ValidationError)
	email = email.strip().lower()
	if validate_email_address(email, throw=True) != email:
		frappe.throw(_("Enter a valid email address."), frappe.ValidationError)
	return email


def _optional_full_name(full_name: str | None) -> str | None:
	return None if full_name is None else _required_full_name(full_name)


def _required_full_name(full_name: str) -> str:
	full_name = require_text(full_name, _("Enter your full name."))
	if len(full_name) > FULL_NAME_MAX_LENGTH:
		frappe.throw(_("Use a shorter name."), frappe.ValidationError)
	return full_name


def _known_product(product: str | None) -> str | None:
	"""A guest names the product only to label funnel events, so an unknown one is dropped."""
	return product if product and frappe.db.exists("Product", product) else None
