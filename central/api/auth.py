from __future__ import annotations

import secrets

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, escape_html, random_string, validate_email_address

from central.identity.doctype.team_invitation.team_invitation import get_invitation_by_token
from central.users import CENTRAL_USER_ROLE, get_pending_invitations

# Signup is OTP-based: `sign_up` emails a 6-digit code and caches the pending
# signup (no User yet, so an abandoned signup leaves nothing behind — simpler than
# a holding DocType). `verify_signup` creates the User on a correct code, then logs
# the new user in so onboarding continues authenticated.

OTP_TTL_SECONDS = 10 * 60
MAX_OTP_ATTEMPTS = 5


class SignupCodeExpiredError(frappe.ValidationError):
	"""The pending signup expired, so the user must start the signup again."""


class SignupLockedError(frappe.ValidationError):
	"""Too many incorrect codes locked the pending signup until it expires."""


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
	"""Send a sign-in code to an enabled account without revealing whether it exists.

	The attempt policy is static, so returning it discloses nothing about the account."""
	email = _validated_email(email)
	if frappe.db.get_value("User", {"email": email}, "enabled"):
		pending = frappe.cache.get_value(_login_otp_key(email))
		if not pending or pending.get("attempts", 0) < MAX_OTP_ATTEMPTS:
			_send_login_code(email, attempts=pending.get("attempts", 0) if pending else 0)
	return {
		"message": _("If this email has an active account, we sent a sign-in code."),
		"max_attempts": MAX_OTP_ATTEMPTS,
		"lockout_minutes": OTP_TTL_SECONDS // 60,
	}


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
	email = _validated_email(email)
	if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
		_reject_login_code()
	lock_key = frappe.cache.make_key(f"login:otp:verify:{email}")
	with frappe.cache.lock(lock_key, timeout=10):
		user = _consume_login_code(email, code)
	frappe.local.login_manager.login_as(user.name)
	return {"user": user.name}


def _consume_login_code(email: str, code: str):
	"""Check attempts and remove a code while its email is locked."""
	pending = frappe.cache.get_value(_login_otp_key(email), use_local_cache=False)
	if not pending or pending.get("attempts", 0) >= MAX_OTP_ATTEMPTS:
		_reject_login_code()

	if not secrets.compare_digest(str(pending["code"]), code):
		pending["attempts"] += 1
		frappe.cache.set_value(_login_otp_key(email), pending, expires_in_sec=OTP_TTL_SECONDS)
		_reject_login_code()

	user = frappe.db.get_value("User", {"email": email}, ["name", "enabled"], as_dict=True)
	if not user or not user.enabled:
		_reject_login_code()
	frappe.cache.delete_value(_login_otp_key(email))
	return user


def _reject_login_code() -> None:
	"""Refuse a sign-in code with one message, so the reason never reveals an account."""
	frappe.throw(
		_("That code is incorrect or has expired. Check your latest email, or request a new code."),
		frappe.ValidationError,
	)


def _login_otp_key(email: str) -> str:
	return f"login:otp:{email}"


def _validated_email(email: str) -> str:
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
	email = _validated_email(email)
	full_name = full_name.strip() if isinstance(full_name, str) else ""
	if not full_name:
		frappe.throw(_("Full name is required."), frappe.ValidationError)

	existing_user = frappe.db.get_value("User", email, "enabled")
	if existing_user == 0:
		frappe.throw(
			_("This account is disabled. Contact support to restore access."), frappe.ValidationError
		)
	if existing_user is not None:
		return 0, _("An account with this email already exists.")

	_enforce_signup_limit()
	pending = frappe.cache.get_value(_otp_key(email))
	if pending and pending.get("attempts", 0) >= MAX_OTP_ATTEMPTS:
		_throw_signup_locked()
	_send_signup_code(email, full_name, attempts=pending.get("attempts", 0) if pending else 0)
	return 1, _("Check your email for your verification code.")


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
	email = _validated_email(email)
	pending = frappe.cache.get_value(_otp_key(email))
	if not pending:
		_throw_signup_expired()
	if pending.get("attempts", 0) >= MAX_OTP_ATTEMPTS:
		_throw_signup_locked()
	_send_signup_code(email, pending["full_name"], attempts=pending.get("attempts", 0))
	return 1, _("We sent a new verification code.")


# nosemgrep: guest-whitelisted-method -- the one-time code and attempt limit authenticate the signup.
@frappe.whitelist(allow_guest=True, methods=["POST"])
def verify_signup(email: str, code: str) -> dict:
	"""Verify the code, create the User, accept the pending invitations, and log the
	user in. A user with no team creates one in console onboarding."""
	email = _validated_email(email)
	code = (code or "").strip()
	pending = frappe.cache.get_value(_otp_key(email))

	if not pending:
		_throw_signup_expired()
	if pending.get("attempts", 0) >= MAX_OTP_ATTEMPTS:
		_throw_signup_locked()

	if not secrets.compare_digest(str(pending.get("code", "")), code):
		pending["attempts"] = pending.get("attempts", 0) + 1
		frappe.cache.set_value(_otp_key(email), pending, expires_in_sec=OTP_TTL_SECONDS)
		if pending["attempts"] >= MAX_OTP_ATTEMPTS:
			_throw_signup_locked()
		frappe.throw(_("That code is incorrect. Try again."), frappe.ValidationError)

	user = _create_verified_user(email, pending["full_name"])
	frappe.cache.delete_value(_otp_key(email))
	frappe.local.login_manager.login_as(user.name)

	for name in get_pending_invitations(user.name):
		frappe.get_doc("Team Invitation", name).accept()
	return {"user": user.name}


# nosemgrep: guest-whitelisted-method -- the emailed token verifies the address, and the IP rate limit applies.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=OTP_TTL_SECONDS, methods="POST")
def sign_up_with_invitation(token: str, full_name: str) -> dict:
	"""Create the invited user's account and join the team.

	The emailed token verifies the address. An existing account must sign in instead."""
	full_name = full_name.strip() if isinstance(full_name, str) else ""
	if not full_name:
		frappe.throw(_("Full name is required."), frappe.ValidationError)

	invitation = get_invitation_by_token(token)
	if not invitation.is_pending:
		frappe.throw(_("This invitation is no longer valid."), frappe.ValidationError)
	if frappe.db.exists("User", invitation.email):
		frappe.throw(
			_("An account with this email already exists. Sign in to accept."), frappe.ValidationError
		)

	_enforce_signup_limit()
	user = _create_verified_user(invitation.email, full_name)
	frappe.local.login_manager.login_as(user.name)
	# Only this invitation: the others for the email stay pending for the user to answer.
	invitation.accept()
	return {"user": user.name, "team": invitation.team}


def _otp_key(email: str) -> str:
	return f"signup:otp:{email}"


def _throw_signup_expired() -> None:
	frappe.throw(_("Your code has expired. Start again to get a new code."), SignupCodeExpiredError)


def _throw_signup_locked() -> None:
	frappe.throw(
		_("Too many incorrect codes. Wait {0} minutes, then start again.").format(OTP_TTL_SECONDS // 60),
		SignupLockedError,
	)


def _send_signup_code(email: str, full_name: str, attempts: int = 0) -> None:
	is_sent = _send_code(
		email,
		_otp_key(email),
		{"full_name": full_name, "attempts": attempts},
		_("Your Frappe Cloud verification code"),
		"Signup verification email failed",
	)
	if not is_sent:
		frappe.throw(
			_("We could not send a code to this email address. Check the address and try again."),
			frappe.ValidationError,
		)


def _send_code(email: str, key: str, pending: dict, subject: str, failure_title: str) -> bool:
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
		# A mail error can queue its own message; the caller decides what the user reads.
		frappe.clear_messages()
		return False
	return True


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
