import secrets

import frappe
import requests
from frappe import _

from central.integrations.oauth.oauth import get_provider

GRAPH_URL = "https://graph.facebook.com/v23.0"
ROUTE = "Meta Webhook Route"
PIN_MISMATCH = 133005  # Graph error code: the number has another two-step PIN

# Refusal codes: Pilot passes on only the error text, and the site shows its own message for each
WABA_IN_USE = "waba_in_use"  # another site has the account
NO_WABA = "no_waba"  # the sign-in shared no account
NO_PHONE_NUMBER = "no_phone_number"
PHONE_NUMBER_UNCLEAR = "phone_number_unclear"  # more than one number could be the new one
PIN_CHANGED = "pin_changed"  # register failed after the PIN change: connecting again finishes it


def connect_whatsapp(access_token: str, team: str, server: str | None, site: str) -> dict:
	"""After Meta's code exchange: ready the signed-in WhatsApp Business Account (WABA) to send and
	receive, route its webhooks to `site`, and return what the site needs to use it."""
	config = get_provider("meta")
	waba_id = get_waba_id(access_token, config.client_id, config.get_password("client_secret"))
	check_route(waba_id, site)

	number = get_new_number(waba_id, access_token)
	phone_id = number["id"]
	call_graph("POST", f"{waba_id}/subscribed_apps", access_token)
	pin = f"{secrets.randbelow(10**6):06d}"
	register(phone_id, access_token, pin)

	webhook_secret = secrets.token_urlsafe(32)
	save_route(waba_id, team, server, site, webhook_secret)
	return {
		"access_token": access_token,
		"app_id": config.client_id,
		"waba_id": waba_id,
		"phone_id": phone_id,
		"pin": pin,
		"webhook_secret": webhook_secret,
		# for the site to name the account; Meta may leave either out
		"display_phone_number": number.get("display_phone_number"),
		"verified_name": number.get("verified_name"),
	}


def get_waba_id(access_token: str, app_id: str, app_secret: str) -> str:
	"""The WABA the user picked in Meta's sign-in; the token's granular scopes name it."""
	token = call_graph("GET", "debug_token", f"{app_id}|{app_secret}", params={"input_token": access_token})
	for scope in token["data"].get("granular_scopes", []):
		if scope.get("scope") == "whatsapp_business_management" and scope.get("target_ids"):
			return scope["target_ids"][0]
	refuse_with(NO_WABA)


def get_new_number(waba_id: str, access_token: str) -> dict:
	"""The number just signed in, with its ID, number and business name. Embedded Signup adds one
	number that is not on the Cloud API yet; an account with a single number is that number signed
	in again."""
	fields = "id,platform_type,display_phone_number,verified_name"
	numbers = call_graph("GET", f"{waba_id}/phone_numbers", access_token, params={"fields": fields})["data"]
	new = [n for n in numbers if n.get("platform_type") == "NOT_APPLICABLE"] or numbers
	if not new:
		refuse_with(NO_PHONE_NUMBER)
	if len(new) > 1:
		# a wrong guess would change the two-step PIN of, and re-register, a number in use
		refuse_with(PHONE_NUMBER_UNCLEAR)
	return new[0]


def register(phone_id: str, access_token: str, pin: str) -> None:
	"""Register the number for the Cloud API with `pin` as its two-step PIN. Its PIN is replaced
	only when it already has another one, so a failed register leaves a number's PIN as it was."""
	path, data = f"{phone_id}/register", {"messaging_product": "whatsapp", "pin": pin}
	body = call_graph("POST", path, access_token, check=False, json=data)
	if "error" not in body:
		return
	if body["error"].get("code") != PIN_MISMATCH:
		refuse(body)
	call_graph("POST", phone_id, access_token, json={"pin": pin})
	body = call_graph("POST", path, access_token, check=False, json=data)
	if "error" in body:
		refuse_with(PIN_CHANGED)


def check_route(waba_id: str, site: str) -> None:
	"""One site per WABA: another site's account is refused before Meta is changed for it."""
	refuse_other_site(frappe.db.get_value(ROUTE, waba_id, "site"), site)


def refuse_other_site(routed_site: str | None, site: str) -> None:
	if routed_site and routed_site != site:
		refuse_with(WABA_IN_USE)


def save_route(waba_id: str, team: str, server: str | None, site: str, webhook_secret: str) -> None:
	values = {"team": team, "server": server, "site": site, "webhook_secret": webhook_secret}
	# a Pilot call: no signed-in user, the credential and the site were checked by the caller
	if not frappe.db.exists(ROUTE, waba_id):
		try:
			frappe.new_doc(ROUTE, waba_id=waba_id, **values).insert(ignore_permissions=True)
			return
		except frappe.DuplicateEntryError:
			pass  # another sign-in made the route meanwhile: check it below
	# another sign-in may have routed the WABA since check_route: check the site again on the locked row
	route = frappe.get_doc(ROUTE, waba_id, for_update=True)
	refuse_other_site(route.site, site)
	route.update(values)
	route.save(ignore_permissions=True)


def disconnect_whatsapp(waba_id: str, team: str, server: str | None) -> None:
	"""Stop routing the WABA's webhooks. Only the server they go to can stop them."""
	route = frappe.db.get_value(ROUTE, waba_id, ["team", "server"], as_dict=True)
	if not route:
		return
	if (route.team, route.server) != (team, server):
		frappe.throw(
			_("This WhatsApp Business Account is not connected to this server"), frappe.PermissionError
		)
	# a Pilot call: no signed-in user, the team and server were checked above
	frappe.delete_doc(ROUTE, waba_id, ignore_permissions=True)


def delete_routes(**filters) -> None:
	"""Stop routing the WABAs whose site or server is gone. A later sign-in can route them again."""
	for waba_id in frappe.get_all(ROUTE, filters, pluck="name"):
		# a system cleanup: a server's termination, a site's deletion or the site's own 410
		frappe.delete_doc(ROUTE, waba_id, ignore_permissions=True)


def call_graph(method: str, path: str, access_token: str, check: bool = True, **kwargs) -> dict:
	"""Call the Graph API. With `check` off, a refusal comes back as the body with its "error"."""
	response = requests.request(
		method,
		f"{GRAPH_URL}/{path}",
		headers={"Authorization": f"Bearer {access_token}"},
		timeout=30,
		allow_redirects=False,
		**kwargs,
	)
	body = response.json()
	if response.ok:
		return body
	body.setdefault("error", {})
	if check:
		refuse(body)
	return body


def refuse_with(code: str) -> None:
	# nosemgrep: frappe-missing-translate-function-python, central-untranslated-message -- a code the site matches on, never shown
	frappe.throw(code)


def refuse(body: dict) -> None:
	# Graph's message says what failed and never holds a token or the PIN
	frappe.throw(_("Meta refused the request: {0}").format(body["error"].get("message")))
