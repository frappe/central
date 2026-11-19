"""Sign a V2 site in to an OAuth provider in one click: a mailbox (mail providers) or a WhatsApp account (meta).

Central holds Frappe Cloud's app for each provider; a site reaches `get_active_providers`, `start`, `relay_token` and `disconnect` through its Pilot.
`central.api.email_oauth` is the old path of these endpoints, kept for live sites.
"""

from urllib.parse import urlencode

import frappe
from frappe import _

from central.api.pilot import pilot_credential_auth
from central.iam import can
from central.integrations.oauth.meta import connect_whatsapp, disconnect_whatsapp
from central.integrations.oauth.oauth import (
	CALLBACK_PATH,
	PROVIDER,
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
def get_active_providers() -> dict[str, str | None]:
	"""Called by a site through its Pilot: the providers a site can sign in with right now.
	Google's comes with its client ID, which a Google Workspace admin looks up to allow the app."""
	providers = frappe.get_all(
		PROVIDER, filters={"enabled": 1}, fields=["name", "client_id"], order_by="name"
	)
	return {p.name: p.client_id if p.name == "google" else None for p in providers}


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
		remember_code_owner(code, note)
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
	credential = frappe.local.pilot_credential
	owner = {}
	if grant_type == "authorization_code":  # initial exchange of the authorization code for a token
		owner = claim_code(code, credential.team, credential.server)
	# the site whose return URL the sign-in checked; a refresh or a domain with no site has none
	site = owner.get("site")
	if provider == "meta" and not site:
		frappe.throw(_("This sign-in did not come from a site on this server"), frappe.PermissionError)
	token = exchange_token(
		provider,
		grant_type,
		code=code,
		code_verifier=code_verifier,
		refresh_token=refresh_token,
		scope=scope,
	)
	if provider == "meta":
		return connect_whatsapp(token["access_token"], credential.team, credential.server, site)
	return token


# nosemgrep: guest-whitelisted-method -- pilot_credential_auth verifies the caller below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def disconnect(waba_id: str) -> None:
	"""Called by a site through its Pilot when it deletes a WhatsApp account: stop sending it that account's Meta webhooks."""
	credential = frappe.local.pilot_credential
	disconnect_whatsapp(waba_id, credential.team, credential.server)
