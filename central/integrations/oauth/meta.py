import secrets

import frappe
import requests
from frappe import _

from central.integrations.oauth.oauth import get_provider

GRAPH_URL = "https://graph.facebook.com/v23.0"
ROUTE = "Meta Webhook Route"


def connect_whatsapp(access_token: str, team: str, server: str | None, site: str) -> dict:
	"""After Meta's code exchange: ready the signed-in WhatsApp Business Account (WABA) to send and
	receive, route its webhooks to `site`, and return what the site needs to use it."""
	config = get_provider("meta")
	waba_id = get_waba_id(access_token, config.client_id, config.get_password("client_secret"))
	check_route(waba_id, site)

	numbers = call_graph("GET", f"{waba_id}/phone_numbers", access_token)["data"]
	if not numbers:
		frappe.throw(
			_("This WhatsApp Business Account has no phone number. Add one at Meta, then try again.")
		)
	# Embedded Signup adds one number to the account, so the first is the one just signed in
	phone_id = numbers[0]["id"]

	call_graph("POST", f"{waba_id}/subscribed_apps", access_token)
	pin = f"{secrets.randbelow(10**6):06d}"
	call_graph(
		"POST", f"{phone_id}/register", access_token, json={"messaging_product": "whatsapp", "pin": pin}
	)

	webhook_secret = secrets.token_urlsafe(32)
	save_route(waba_id, team, server, site, webhook_secret)
	return {
		"access_token": access_token,
		"app_id": config.client_id,
		"waba_id": waba_id,
		"phone_id": phone_id,
		"pin": pin,
		"webhook_secret": webhook_secret,
	}


def get_waba_id(access_token: str, app_id: str, app_secret: str) -> str:
	"""The WABA the user picked in Meta's sign-in; the token's granular scopes name it."""
	token = call_graph("GET", "debug_token", f"{app_id}|{app_secret}", params={"input_token": access_token})
	for scope in token["data"].get("granular_scopes", []):
		if scope.get("scope") == "whatsapp_business_management" and scope.get("target_ids"):
			return scope["target_ids"][0]
	frappe.throw(_("Meta did not share a WhatsApp Business Account. Sign in again and pick one."))


def check_route(waba_id: str, site: str) -> None:
	"""One site per WABA: another site's account is refused before Meta is changed for it."""
	routed_site = frappe.db.get_value(ROUTE, waba_id, "site")
	if routed_site and routed_site != site:
		frappe.throw(
			_(
				"This WhatsApp Business Account is already connected to another Frappe Cloud site. Disconnect it there first."
			),
			title=_("Account in use"),
		)


def save_route(waba_id: str, team: str, server: str | None, site: str, webhook_secret: str) -> None:
	route = (
		frappe.get_doc(ROUTE, waba_id, for_update=True)
		if frappe.db.exists(ROUTE, waba_id)
		else frappe.new_doc(ROUTE, waba_id=waba_id)
	)
	route.update({"team": team, "server": server, "site": site, "webhook_secret": webhook_secret})
	# a Pilot call: no signed-in user, the credential and the site were checked by the caller
	route.save(ignore_permissions=True)


def disconnect_whatsapp(waba_id: str, site: str) -> None:
	"""Stop routing the WABA's webhooks. Only the site they go to can stop them."""
	routed_site = frappe.db.get_value(ROUTE, waba_id, "site")
	if not routed_site:
		return
	if routed_site != site:
		frappe.throw(
			_("This WhatsApp Business Account is not connected to this site"), frappe.PermissionError
		)
	# a Pilot call: no signed-in user, the site was checked above
	frappe.delete_doc(ROUTE, waba_id, ignore_permissions=True)


def call_graph(method: str, path: str, access_token: str, **kwargs) -> dict:
	response = requests.request(
		method,
		f"{GRAPH_URL}/{path}",
		headers={"Authorization": f"Bearer {access_token}"},
		timeout=30,
		allow_redirects=False,
		**kwargs,
	)
	body = response.json()
	if not response.ok:
		# Graph's message says what failed and never holds a token or the PIN
		frappe.throw(_("Meta refused the request: {0}").format(body.get("error", {}).get("message")))
	return body
