from __future__ import annotations

import secrets

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, escape_html, random_string, validate_email_address

from central.iam import get_user_team_names
from central.users import CENTRAL_USER_ROLE
from central.utils.inputs import require_secret

# Signup is OTP-based: `sign_up` emails a 6-digit code and caches the pending
# signup (no User yet, so an abandoned signup leaves nothing behind — simpler than
# a holding DocType). `verify_signup` creates the User on a correct code — which
# fires `bootstrap_user_team` (central/users.py) to provision the Central role and
# personal Team — then logs the new user in so onboarding continues authenticated.

OTP_TTL_SECONDS = 10 * 60
MAX_OTP_ATTEMPTS = 5


# nosemgrep: guest-whitelisted-method -- login requires an emailed code and limits requests by IP and email.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=OTP_TTL_SECONDS, methods="POST")
@rate_limit(
	key="email",
	ip_based=False,
	endpoint="central.login.code_send",
	limit=5,
	seconds=OTP_TTL_SECONDS,
	methods="POST",
)
def request_login_code(email: str) -> dict:
	"""Send a sign-in code to an enabled account without revealing whether it exists."""
	email = _login_email(email)
	if frappe.db.get_value("User", {"email": email}, "enabled"):
		pending = frappe.cache.get_value(_login_otp_key(email))
		if not pending or pending.get("attempts", 0) < MAX_OTP_ATTEMPTS:
			_send_login_code(email, attempts=pending.get("attempts", 0) if pending else 0)
	return {"message": _("If this email has an active account, we sent a sign-in code.")}


# nosemgrep: guest-whitelisted-method -- a short-lived code and attempt limit authenticate the user.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=OTP_TTL_SECONDS, methods="POST")
@rate_limit(
	key="email",
	ip_based=False,
	endpoint="central.login.code_verify",
	limit=10,
	seconds=OTP_TTL_SECONDS,
	methods="POST",
)
def verify_login_code(email: str, code: str) -> dict:
	"""Consume a valid email code and create the user's session."""
	email = _login_email(email)
	if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
		frappe.throw(_("Invalid or expired sign-in code."), frappe.ValidationError)
	lock_key = frappe.cache.make_key(f"login:otp:verify:{email}")
	with frappe.cache.lock(lock_key, timeout=10):
		user = _consume_login_code(email, code)
	frappe.local.login_manager.login_as(user.name)
	return {"user": user.name}


def _consume_login_code(email: str, code: str):
	"""Check attempts and remove a code while its email is locked."""
	pending = frappe.cache.get_value(_login_otp_key(email), use_local_cache=False)
	if not pending or pending.get("attempts", 0) >= MAX_OTP_ATTEMPTS:
		frappe.throw(_("Invalid or expired sign-in code."), frappe.ValidationError)

	if not secrets.compare_digest(str(pending["code"]), code):
		pending["attempts"] += 1
		frappe.cache.set_value(_login_otp_key(email), pending, expires_in_sec=OTP_TTL_SECONDS)
		frappe.throw(_("Invalid or expired sign-in code."), frappe.ValidationError)

	user = frappe.db.get_value("User", {"email": email}, ["name", "enabled"], as_dict=True)
	if not user or not user.enabled:
		frappe.throw(_("Invalid or expired sign-in code."), frappe.ValidationError)
	frappe.cache.delete_value(_login_otp_key(email))
	return user


def _login_otp_key(email: str) -> str:
	return f"login:otp:{email}"


def _login_email(email: str) -> str:
	if not isinstance(email, str) or len(email) > 254:
		frappe.throw(_("Enter a valid email address."), frappe.ValidationError)
	email = email.strip().lower()
	if validate_email_address(email, throw=True) != email:
		frappe.throw(_("Enter a valid email address."), frappe.ValidationError)
	return email


def _send_login_code(email: str, attempts: int) -> None:
	_send_code(
		email,
		_login_otp_key(email),
		{"attempts": attempts},
		_("Your Frappe Cloud sign-in code"),
		"Sign-in verification email failed",
	)


# nosemgrep: guest-whitelisted-method -- signup requires guest access and enforces the site signup limit.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=OTP_TTL_SECONDS, methods="POST")
@rate_limit(
	key="email",
	ip_based=False,
	endpoint="central.signup.code_send",
	limit=5,
	seconds=OTP_TTL_SECONDS,
	methods="POST",
)
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
	pending = frappe.cache.get_value(_otp_key(email))
	if pending and pending.get("attempts", 0) >= MAX_OTP_ATTEMPTS:
		frappe.throw(_("Too many incorrect codes. Please try again later."), frappe.ValidationError)
	_send_signup_code(email, full_name, attempts=pending.get("attempts", 0) if pending else 0)
	return 1, _("Please check your email for your verification code")


# nosemgrep: guest-whitelisted-method -- a pending signup and route rate limit constrain resends.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=OTP_TTL_SECONDS, methods="POST")
@rate_limit(
	key="email",
	ip_based=False,
	endpoint="central.signup.code_send",
	limit=5,
	seconds=OTP_TTL_SECONDS,
	methods="POST",
)
def resend_signup_code(email: str) -> tuple[int, str]:
	"""Re-issue a fresh code for a pending signup."""
	email = email.strip().lower()
	pending = frappe.cache.get_value(_otp_key(email))
	if not pending:
		frappe.throw(_("Start the signup again — your session expired."), frappe.ValidationError)
	if pending.get("attempts", 0) >= MAX_OTP_ATTEMPTS:
		frappe.throw(_("Too many incorrect codes. Please try again later."), frappe.ValidationError)
	_send_signup_code(email, pending["full_name"], attempts=pending.get("attempts", 0))
	return 1, _("A new verification code is on its way")


# nosemgrep: guest-whitelisted-method -- the one-time code and attempt limit authenticate the signup.
@frappe.whitelist(allow_guest=True, methods=["POST"])
def verify_signup(email: str, code: str) -> dict:
	"""Verify the code, create the User (which bootstraps the personal Team), and
	log the user in so onboarding continues authenticated."""
	email = email.strip().lower()
	code = (code or "").strip()
	pending = frappe.cache.get_value(_otp_key(email))

	if not pending:
		frappe.throw(_("Your verification code expired. Please sign up again."), frappe.ValidationError)
	if pending.get("attempts", 0) >= MAX_OTP_ATTEMPTS:
		frappe.throw(_("Too many incorrect codes. Please try again later."), frappe.ValidationError)

	if not secrets.compare_digest(str(pending.get("code", "")), code):
		pending["attempts"] = pending.get("attempts", 0) + 1
		frappe.cache.set_value(_otp_key(email), pending, expires_in_sec=OTP_TTL_SECONDS)
		if pending["attempts"] >= MAX_OTP_ATTEMPTS:
			frappe.throw(_("Too many incorrect codes. Please try again later."), frappe.ValidationError)
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


def _send_signup_code(email: str, full_name: str, attempts: int = 0) -> None:
	_send_code(
		email,
		_otp_key(email),
		{"full_name": full_name, "attempts": attempts},
		_("Your Frappe Cloud verification code"),
		"Signup verification email failed",
	)


def _send_code(email: str, key: str, pending: dict, subject: str, failure_title: str) -> None:
	code = f"{secrets.randbelow(900000) + 100000}"
	frappe.cache.set_value(
		key,
		{**pending, "code": code},
		expires_in_sec=OTP_TTL_SECONDS,
	)
	try:
		frappe.sendmail(
			recipients=[email],
			subject=subject,
			template="verification_code",
			args={"code": code, "expires_minutes": OTP_TTL_SECONDS // 60},
			now=True,
		)
	except Exception:
		frappe.log_error(title=failure_title)


def _create_verified_user(email: str, full_name: str):
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": escape_html(full_name),
			"enabled": 1,
			"new_password": random_string(10),
			"user_type": "Website User",
			"roles": [{"role": role} for role in _signup_roles()],
		}
	)
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


def _enforce_signup_limit() -> None:
	limit = cint(frappe.get_system_settings("max_signups_allowed_per_hour") or 300)
	if frappe.db.get_creation_count("User", 60) >= limit:
		frappe.throw(
			_("Too many users signed up recently. Please try again in an hour."),
			frappe.TooManyRequestsError,
		)


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=5, seconds=60 * 60, methods="POST")
def change_password(old_password: str, new_password: str) -> dict:
	"""Change the signed-in user's password, proving they know the current one.

	Only ever acts on `frappe.session.user` — there is no user parameter to
	abuse. Rate-limited so the old-password check can't be used to brute-force
	an unattended session. Other sessions are signed out (the current one is
	kept), so a stolen session dies with the password change."""
	from frappe.core.doctype.user.user import handle_password_test_fail, test_password_strength
	from frappe.utils.password import check_password, update_password

	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Sign in to change your password."), frappe.PermissionError)

	# Typed at the trust boundary: a JSON body can put a list or dict here, and
	# the password helpers below would raise an unhandled error on one.
	old_password = require_secret(old_password, _("Enter your current password."))
	new_password = require_secret(new_password, _("Enter a new password."))

	# A wrong password must NOT re-raise AuthenticationError: frappe's request
	# handler treats that as a failed login and tears down the session, so a
	# typo here would sign the user out of the console. Re-raise it as a plain
	# validation error instead — the rate limit above is what stops guessing.
	try:
		check_password(user, old_password)
	except frappe.AuthenticationError:
		frappe.throw(_("Your current password is incorrect."), frappe.ValidationError)

	if new_password == old_password:
		frappe.throw(_("Choose a password you haven't used here before."), frappe.ValidationError)

	# Honour the site's password policy, same as the reset flow does.
	feedback = test_password_strength(new_password).get("feedback")
	if feedback and not feedback.get("password_policy_validation_passed", False):
		handle_password_test_fail(feedback)

	update_password(user, new_password, logout_all_sessions=True)
	frappe.db.set_value("User", user, "last_password_reset_date", frappe.utils.today())
	return {"changed": True}
