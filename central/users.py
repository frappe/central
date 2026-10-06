from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, escape_html, random_string, today

from central.identity.email_code import EmailCode

CENTRAL_USER_ROLE = "Central User"


def send_sign_in_code(email: str, full_name: str | None = None) -> None:
	"""Email a code to any address. A new address gets an account when the code is verified.

	A disabled account gets a notice instead of a code, so the caller cannot tell it apart."""
	user = _find_user(email)
	if user and not user.enabled:
		_send_disabled_notice(email)
	elif user:
		EmailCode(email).send(_("{0} is your Frappe Cloud sign-in code"), _("Sign in to Frappe Cloud"))
	else:
		EmailCode(email).send(
			_("{0} is your Frappe Cloud signup code"), _("Create your Frappe Cloud account"), full_name
		)


def sign_in_with_code(email: str, code: str, full_name: str | None = None) -> dict:
	"""Sign in with a verified code, creating the account for a new address.

	A new address needs a name. Without one the code stays valid, so the person can add it."""
	email_code = EmailCode(email)
	with email_code.lock():
		pending = email_code.verify(code)
		user = _find_user(email)
		if user and not user.enabled:
			_throw_disabled()

		full_name = full_name or pending.get("full_name")
		if not user and not full_name:
			return {"needs_name": True}

		name = user.name if user else create_user(email, full_name).name
		email_code.discard()

	frappe.local.login_manager.login_as(name)
	if not user:
		for invitation in get_pending_invitations(name):
			frappe.get_doc("Team Invitation", invitation).accept()
	return {"user": name}


def create_user(email: str, full_name: str):
	"""Create a Website User whose email is already verified."""
	_enforce_signup_limit()
	roles = {CENTRAL_USER_ROLE, frappe.get_single_value("Portal Settings", "default_role")}
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": escape_html(full_name),
			"enabled": 1,
			"new_password": random_string(10),
			"user_type": "Website User",
			"roles": [{"role": role} for role in roles if role],
		}
	)
	user.flags.ignore_password_policy = True
	user.flags.no_welcome_mail = True
	# A guest creates the account, and a guest has no User create permission.
	user.insert(ignore_permissions=True)
	return user


def grant_central_user_role(doc, method: str | None = None) -> None:
	"""Give a newly created user the Central User role.

	A new user gets no team here. An invited user joins the invited team when the
	signup accepts the invitation. Anyone else creates a team in console onboarding."""
	if _should_skip_role_grant(doc):
		return

	if CENTRAL_USER_ROLE not in {row.role for row in doc.roles}:
		doc.add_roles(CENTRAL_USER_ROLE)


def get_pending_invitations(user: str) -> list[str]:
	return frappe.get_all(
		"Team Invitation",
		filters={"email": user, "status": "Pending", "expires_on": [">=", today()]},
		pluck="name",
		order_by="creation asc",
	)


def _find_user(email: str):
	return frappe.db.get_value("User", {"email": email}, ["name", "enabled"], as_dict=True)


def _send_disabled_notice(email: str) -> None:
	frappe.sendmail(
		recipients=[email],
		subject=_("Your Frappe Cloud account is disabled"),
		template="notification",
		args={
			"title": _("Your account is disabled"),
			"body": _(
				"Someone tried to sign in to Frappe Cloud with this email. Contact support to restore access."
			),
		},
	)


def _throw_disabled() -> None:
	frappe.throw(_("This account is disabled. Contact support to restore access."), frappe.ValidationError)


def _enforce_signup_limit() -> None:
	limit = cint(frappe.get_system_settings("max_signups_allowed_per_hour") or 300)
	if frappe.db.get_creation_count("User", 60) >= limit:
		frappe.throw(
			_("Too many users signed up recently. Please try again in an hour."),
			frappe.TooManyRequestsError,
		)


def _should_skip_role_grant(doc) -> bool:
	if not doc.enabled:
		return True
	if getattr(frappe.flags, "in_install", False) or getattr(frappe.flags, "in_migrate", False):
		return True
	if not frappe.db.exists("Role", CENTRAL_USER_ROLE):
		return True
	return False
