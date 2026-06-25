from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, escape_html, random_string
from frappe.utils.oauth import get_oauth2_authorize_url, get_oauth_keys
from frappe.utils.password import get_decrypted_password


@frappe.whitelist(allow_guest=True, methods=["POST"])
def sign_up(email: str, full_name: str) -> tuple[int, str]:
	"""Create a Central Website User even when public website signup is disabled."""
	email = email.strip().lower()
	full_name = full_name.strip()
	if not full_name:
		frappe.throw(_("Full name is required."), frappe.ValidationError)

	existing_user = frappe.db.get_value("User", email, "enabled")
	if existing_user is not None:
		return (0, _("Already Registered")) if existing_user else (0, _("Registered but disabled"))

	_enforce_signup_limit()
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": escape_html(full_name),
			"enabled": 1,
			"new_password": random_string(10),
			"user_type": "Website User",
		}
	)
	user.flags.ignore_permissions = True
	user.flags.ignore_password_policy = True
	user.insert()

	default_role = frappe.get_single_value("Portal Settings", "default_role")
	if default_role:
		user.add_roles(default_role)

	# TODO(SMB signup): redirect product signups to domain selection before provisioning.
	frappe.cache.hset("redirect_after_login", user.name, "/dashboard/servers")
	if user.flags.email_sent:
		return 1, _("Please check your email for verification")
	return 2, _("The verification email could not be sent. Please contact your administrator.")


def build_auth_context() -> dict:
	return {
		"user": frappe.session.user or "Guest",
		"provider_logins": _provider_logins(),
	}


def _provider_logins() -> list[dict[str, str]]:
	providers = frappe.get_all(
		"Social Login Key",
		filters={"enable_social_login": 1},
		fields=["name", "client_id", "base_url", "provider_name", "icon"],
		order_by="name",
	)
	return [
		{
			"name": provider.name,
			"label": provider.provider_name,
			"icon": provider.icon or "",
			"auth_url": get_oauth2_authorize_url(provider.name, "/dashboard/servers"),
		}
		for provider in providers
		if _provider_is_configured(provider)
	]


def _provider_is_configured(provider) -> bool:
	client_secret = get_decrypted_password(
		"Social Login Key",
		provider.name,
		"client_secret",
		raise_exception=False,
	)
	return bool(provider.client_id and client_secret and provider.base_url and get_oauth_keys(provider.name))


def _enforce_signup_limit() -> None:
	limit = cint(frappe.get_system_settings("max_signups_allowed_per_hour") or 300)
	if frappe.db.get_creation_count("User", 60) >= limit:
		frappe.throw(
			_("Too many users signed up recently. Please try again in an hour."),
			frappe.TooManyRequestsError,
		)
