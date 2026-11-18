"""Frappe Cloud's OAuth app at each provider, and the note that carries one sign-in."""

import hashlib
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import frappe
import requests
from frappe import _
from frappe.utils import get_url
from oauthlib.oauth2 import WebApplicationClient

from central.infrastructure.doctype.site.site import get_server_hostnames

if TYPE_CHECKING:
	from central.central.doctype.oauth_provider.oauth_provider import OAuthProvider

PROVIDER = "OAuth Provider"
CALLBACK_PATH = "/api/method/central.api.oauth.callback"
MAIL_CALLBACK_PATH = "/api/method/frappe.integrations.frappe_providers.email_oauth.callback"
# the one site path each provider's sign-in may return to, so a sign-in never lands in another app
SITE_CALLBACK_PATHS = {
	**dict.fromkeys(("microsoft", "google", "yahoo", "yandex"), MAIL_CALLBACK_PATH),
	"meta": "/api/method/whatsapp.whatsapp.oauth.callback",
}
# Meta's login dialog documents no PKCE parameters; its code is still single use and bound to one server
WITHOUT_PKCE = ("meta",)
NOTE_TTL = 10 * 60
# Pilot keeps only an error's text; the site matches this to fall back to its normal mailbox form
PROVIDER_UNAVAILABLE = "provider_unavailable"


def start_sign_in(
	provider: str,
	state: str,
	code_challenge: str,
	return_url: str,
	team: str,
	server: str | None,
	login_hint: str | None = None,
) -> dict:
	"""Remember where to send the browser back, and return the provider's sign-in link.
	With `login_hint`, the provider goes to that account instead of asking which one."""
	config = get_provider(provider)
	check_return_url(provider, return_url, team, server)
	# the calling site, so a sign-in needs no site name from Pilot
	site = get_host_site(urlsplit(return_url).hostname, team, server)

	frappe.cache.set_value(
		note_key(state),
		{"return_url": return_url, "team": team, "server": server, "site": site},
		expires_in_sec=NOTE_TTL,
	)

	scopes = config.get_scopes()
	params = config.get_query_params()
	if login_hint:
		params["login_hint"] = login_hint
		prompt = " ".join(p for p in params.pop("prompt", "").split() if p != "select_account")
		if prompt:
			params["prompt"] = prompt
	if provider not in WITHOUT_PKCE:
		params.update(code_challenge=code_challenge, code_challenge_method="S256")
	authorize_url = WebApplicationClient(config.client_id).prepare_request_uri(
		config.authorize_url,
		redirect_uri=get_url(CALLBACK_PATH),
		scope=" ".join(scopes),
		state=state,
		**params,
	)
	# the site saves these scopes on its Connected App, so it keeps no list of its own
	return {"authorize_url": authorize_url, "client_id": config.client_id, "scopes": scopes}


def check_return_url(provider: str, return_url: str, team: str, server: str | None) -> None:
	url = urlsplit(return_url)
	schemes = ("https", "http") if frappe.conf.developer_mode else ("https",)
	if (
		url.scheme in schemes
		and "@" not in url.netloc
		and "\\" not in return_url
		and url.path == SITE_CALLBACK_PATHS.get(provider)
		and url.hostname in get_server_hostnames(team, server)
	):
		return
	frappe.throw(
		_("Return URL must be this provider's callback on one of this server's sites"),
		frappe.PermissionError,
	)


def get_host_site(hostname: str, team: str, server: str) -> str | None:
	"""The team's site on `server` that answers on `hostname`: its own address or an active domain."""
	filters = {"team": team, "server": server}
	return frappe.db.exists("Site", {"name": hostname, **filters}) or frappe.db.get_value(
		"Site Domain", {"name": hostname, "status": "Active", **filters}, "site"
	)


def get_sign_in(state: str | None) -> dict | None:
	return frappe.cache.get_value(note_key(state)) if state else None


def mark_login_sent(state: str, note: dict) -> None:
	frappe.cache.set_value(note_key(state), {**note, "login_sent": True}, expires_in_sec=NOTE_TTL)


def forget_sign_in(state: str) -> None:
	frappe.cache.delete_value(note_key(state))


def note_key(state: str) -> str:
	return f"email_oauth:{state}"


def remember_code_owner(code: str, note: dict) -> None:
	"""Remember which server's and site's sign-in got `code`, so only that server can swap it."""
	owner = {"team": note["team"], "server": note["server"], "site": note.get("site")}
	frappe.cache.set_value(code_key(code), owner, expires_in_sec=NOTE_TTL)


def claim_code(code: str | None, team: str, server: str | None) -> dict:
	"""Single use: a code swaps only for the server whose sign-in got it. Returns its owner."""
	key = code_key(code or "")
	owner = frappe.cache.get_value(key)
	frappe.cache.delete_value(key)
	if not owner or (owner["team"], owner["server"]) != (team, server):
		frappe.throw(_("This sign-in code was not given to this server"), frappe.PermissionError)
	return owner


def code_key(code: str) -> str:
	# hashed, so the cache never holds a code that still works
	return f"email_oauth_code:{hashlib.sha256(code.encode()).hexdigest()}"


def exchange_token(provider: str, grant_type: str, **params: str | None) -> dict:
	"""Swap a code or refresh token at the provider with Frappe Cloud's app secret."""
	config = get_provider(provider)
	if grant_type not in ("authorization_code", "refresh_token"):
		frappe.throw(_("Unsupported grant type"))

	data = {
		**params,
		"grant_type": grant_type,
		"client_id": config.client_id,
		"client_secret": config.get_password("client_secret"),
	}
	if grant_type == "authorization_code":
		data["redirect_uri"] = get_url(CALLBACK_PATH)
	if provider in WITHOUT_PKCE:
		data.pop("code_verifier", None)

	response = requests.post(
		config.token_url, data={k: v for k, v in data.items() if v}, timeout=30, allow_redirects=False
	)
	token = response.json()
	if not response.ok:
		# Pilot keeps only this text, so the site can still tell invalid_grant apart (standard OAuth error code)
		frappe.throw(get_token_error(token) or _("The provider refused the token request"))
	return token


def get_token_error(token: dict) -> str | None:
	error = token.get("error")
	if not isinstance(error, dict):
		return error
	# Meta answers with a Graph error; these subcodes are its expired and used codes
	if error.get("error_subcode") in (36007, 36009):
		return "invalid_grant"
	return None


def get_provider(provider: str) -> "OAuthProvider":
	"""The enabled record for `provider`; an enabled one always has a client ID and secret."""
	config = frappe.db.exists(PROVIDER, provider) and frappe.get_cached_doc(PROVIDER, provider)
	if not (config and config.enabled):
		# nosemgrep: frappe-missing-translate-function-python, central-untranslated-message -- a code the site matches on, never shown
		frappe.throw(PROVIDER_UNAVAILABLE)
	return config
