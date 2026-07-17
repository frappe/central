from __future__ import annotations

import secrets

import frappe
from frappe import _
from frappe.utils import cint, escape_html, random_string
from frappe.utils.oauth import get_oauth2_authorize_url, get_oauth_keys
from frappe.utils.password import get_decrypted_password

from central.iam import get_user_team_names
from central.users import CENTRAL_USER_ROLE

# Signup is OTP-based: `sign_up` emails a 6-digit code and caches the pending
# signup (no User yet, so an abandoned signup leaves nothing behind — simpler than
# a holding DocType). `verify_signup` creates the User on a correct code — which
# fires `bootstrap_user_team` (central/users.py) to provision the Central role and
# personal Team — then logs the new user in so onboarding continues authenticated.

# 2 hours
OTP_TTL_SECONDS = 2 * 60 * 60
MAX_OTP_ATTEMPTS = 5


@frappe.whitelist(allow_guest=True, methods=["POST"])
def sign_up(email: str, full_name: str) -> tuple[int, str]:
	"""Start an SMB signup: email a verification code, hold the pending signup in
	cache. The User is created only on `verify_signup`."""
	email = email.strip().lower()
	full_name = full_name.strip()
	if not full_name:
		frappe.throw(_("Full name is required."), frappe.ValidationError)

	existing_user = frappe.db.get_value("User", email, "enabled")
	if existing_user is not None:
		return (0, _("Already Registered")) if existing_user else (0, _("Registered but disabled"))

	_enforce_signup_limit()
	_send_signup_code(email, full_name)
	return 1, _("Please check your email for your verification code")


@frappe.whitelist(allow_guest=True, methods=["POST"])
def resend_signup_code(email: str) -> tuple[int, str]:
	"""Re-issue a fresh code for a pending signup."""
	email = email.strip().lower()
	pending = frappe.cache.get_value(_otp_key(email))
	if not pending:
		frappe.throw(_("Start the signup again — your session expired."), frappe.ValidationError)
	_send_signup_code(email, pending["full_name"])
	return 1, _("A new verification code is on its way")


@frappe.whitelist(allow_guest=True, methods=["POST"])
def verify_signup(email: str, code: str) -> dict:
	"""Verify the code, create the User (which bootstraps the personal Team), and
	log the user in so onboarding continues authenticated."""
	email = email.strip().lower()
	code = (code or "").strip()
	pending = frappe.cache.get_value(_otp_key(email))

	# for developer mode, any 6-digit code passes
	if frappe.conf.developer_mode and pending and len(code) == 6 and code.isdigit():
		pending["code"] = code

	if not pending:
		frappe.throw(_("Your verification code expired. Please sign up again."), frappe.ValidationError)

	if not _code_matches(pending, code):
		pending["attempts"] = pending.get("attempts", 0) + 1
		if pending["attempts"] >= MAX_OTP_ATTEMPTS:
			frappe.cache.delete_value(_otp_key(email))
			frappe.throw(_("Too many incorrect codes. Please sign up again."), frappe.ValidationError)
		frappe.cache.set_value(_otp_key(email), pending, expires_in_sec=OTP_TTL_SECONDS)
		frappe.throw(_("That code is incorrect — try again."), frappe.ValidationError)

	user = _create_verified_user(email, pending["full_name"])
	frappe.cache.delete_value(_otp_key(email))
	frappe.local.login_manager.login_as(user.name)

	teams = get_user_team_names(user.name)
	team = teams[0] if teams else None
	if team:
		_provision_signup_billing(team)
	return {"user": user.name, "team": team}


def _provision_signup_billing(team: str) -> None:
	"""Seed the new team's billing currency from its signup IP and grant the
	matching welcome credits. Best-effort: a geolocation or provisioning hiccup is
	logged, never fatal — the user can still complete their profile from the
	dashboard, which provisions the same way."""
	try:
		from central.billing.payments.provisioning import provision_signup_billing
		from central.geo import get_country_from_ip

		provision_signup_billing(team, get_country_from_ip())
	except Exception:
		frappe.log_error(title="Signup billing provisioning failed")


def _otp_key(email: str) -> str:
	return f"signup:otp:{email}"


def _send_signup_code(email: str, full_name: str) -> None:
	code = f"{secrets.randbelow(900000) + 100000}"
	frappe.cache.set_value(
		_otp_key(email),
		{"full_name": full_name, "code": code, "attempts": 0},
		expires_in_sec=OTP_TTL_SECONDS,
	)
	# Queued (not `now`), and a delivery failure (e.g. no outgoing account in dev)
	# is logged, never fatal — the code is already cached, so signup can proceed.
	try:
		frappe.sendmail(
			recipients=[email],
			subject=_("Your Frappe Cloud verification code"),
			message=_(
				"<p>Your verification code is <strong>{0}</strong>.</p><p>It expires in 10 minutes.</p>"
			).format(code),
			now=True,
		)
	except Exception:
		frappe.log_error(title="Signup verification email failed")


def _code_matches(pending: dict, code: str) -> bool:
	# Demo/dev convenience: any 6-digit code passes (mirrors the UI hint). Fails
	# closed in production.
	if frappe.conf.developer_mode and len(code) == 6 and code.isdigit():
		return True
	return secrets.compare_digest(str(pending.get("code", "")), code)


def _create_verified_user(email: str, full_name: str):
	user = frappe.get_doc({
		"doctype": "User",
		"email": email,
		"first_name": escape_html(full_name),
		"enabled": 1,
		"new_password": random_string(10),
		"user_type": "Website User",
		"roles": [{"role": role} for role in _signup_roles()],
	})
	user.flags.ignore_permissions = True
	user.flags.ignore_password_policy = True
	user.flags.no_welcome_mail = True
	# ignore permissions because we are inserting a user as a website user
	user.insert(ignore_permissions=True)
	return user


def _signup_roles() -> list[str]:
	roles = [CENTRAL_USER_ROLE]
	default_role = frappe.get_single_value("Portal Settings", "default_role")
	if default_role and default_role not in roles:
		roles.append(default_role)
	return roles


def build_auth_context() -> dict:
	return {
		"user": frappe.session.user or "Guest",
		"provider_logins": _provider_logins(),
		"onboarding_complete": _onboarding_complete(),
	}


def _onboarding_complete() -> bool:
	"""True once the user's team owns a live site — the signal the SPA uses to keep a
	brand-new user inside the onboarding funnel (and let a returning one skip it).
	A first-run user (no team or no site yet) is still onboarding."""
	user = frappe.session.user
	if not user or user == "Guest":
		return False
	teams = get_user_team_names(user)
	if not teams:
		return False
	return bool(frappe.db.exists("Site", {"team": ["in", teams], "status": ["!=", "Terminated"]}))


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
