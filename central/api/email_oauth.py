"""Connect a mailbox in one click on a V2 site, for any OAuth mail provider in PROVIDERS.

Central holds Frappe Cloud's app for each provider; a site reaches `get_active_providers`, `start` and `relay_token` through its Pilot.
"""

from urllib.parse import urlencode

import frappe
from frappe import _

from central.api.pilot import pilot_credential_auth
from central.iam import can
from central.integrations.email_oauth.email_oauth import (
	CALLBACK_PATH,
	claim_code,
	exchange_token,
	forget_sign_in,
	get_sign_in,
	mark_login_sent,
	remember_code_owner,
	start_sign_in,
)

LOGIN_PATH = "/dashboard/login"


# nosemgrep: guest-whitelisted-method -- pilot_credential_auth verifies the caller below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def start(
	provider: str, state: str, code_challenge: str, return_url: str, login_hint: str | None = None
) -> dict:
	"""Called by a site through its Pilot: remember where to send the browser back, return the provider's sign-in link."""
	credential = frappe.local.pilot_credential
	return start_sign_in(
		provider, state, code_challenge, return_url, credential.team, credential.server, login_hint
	)


# nosemgrep: guest-whitelisted-method -- pilot_credential_auth verifies the caller below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def get_active_providers() -> list[str]:
	"""Called by a site through its Pilot: the providers a mailbox can sign in with right now."""
	return frappe.get_all("Email OAuth Provider", filters={"enabled": 1}, pluck="name", order_by="name")


# nosemgrep: guest-whitelisted-method -- the provider sends the browser here; the code only goes to the site's team.
@frappe.whitelist(allow_guest=True, methods=["GET"])
def callback(
	state: str | None = None,
	code: str | None = None,
	error: str | None = None,
	error_description: str | None = None,
) -> None:
	"""Every provider sends the browser here. Single use: the note is deleted on the first read."""
	note = get_sign_in(state)
	if not note:
		frappe.respond_as_web_page(
			_("Link expired"),
			_("This sign-in has expired or was already used. Please start again from your site."),
			http_status_code=400,
			primary_action=None,
		)
		return
	# a logged-out browser signs in to Central once, then comes back here with the same code (D3)
	if code and not error and frappe.session.user == "Guest" and not note.get("login_sent"):
		mark_login_sent(state, note)
		back = add_query_params(CALLBACK_PATH, state=state, code=code)
		redirect(add_query_params(LOGIN_PATH, **{"redirect-to": back}))
		return
	forget_sign_in(state)
	redirect(
		add_query_params(note["return_url"], state=state, **site_params(note, code, error, error_description))
	)


def site_params(note: dict, code: str | None, error: str | None, error_description: str | None) -> dict:
	if error or not code:
		return {"error": error or "invalid_request", "error_description": error_description}
	# the code goes only to the site's team, so a stranger's site never gets it (consent phishing)
	if can(frappe.session.user, note["team"], "server:view", server=note["server"]):
		remember_code_owner(code, note["team"], note["server"])
		return {"code": code}
	return {"error": "not_team_member"}


def redirect(location: str) -> None:
	frappe.local.response.type = "redirect"
	frappe.local.response.location = location


def add_query_params(url: str, **params: str | None) -> str:
	return f"{url}{'&' if '?' in url else '?'}{urlencode({k: v for k, v in params.items() if v})}"


# nosemgrep: guest-whitelisted-method -- pilot_credential_auth verifies the caller below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def relay_token(
	provider: str,
	grant_type: str,
	code: str | None = None,
	code_verifier: str | None = None,
	refresh_token: str | None = None,
	scope: str | None = None,
) -> dict:
	"""Called by a site through its Pilot: swap a code or refresh token at the provider using Frappe Cloud's app secret."""
	if grant_type == "authorization_code":  # initial exchange of the authorization code for a token
		credential = frappe.local.pilot_credential
		claim_code(code, credential.team, credential.server)
	return exchange_token(
		provider,
		grant_type,
		code=code,
		code_verifier=code_verifier,
		refresh_token=refresh_token,
		scope=scope,
	)
