import secrets

import frappe
import requests
from frappe import _

from central.integrations.oauth.oauth import get_provider

GRAPH_URL = "https://graph.facebook.com/v23.0"
ROUTE = "Meta Webhook Route"
PIN_MISMATCH = 133005  # Graph error code: the number has another two-step PIN


def connect_whatsapp(access_token: str, team: str, server: str | None, site: str) -> dict:
	"""After Meta's code exchange: ready the signed-in WhatsApp Business Account (WABA) to send and
	receive, route its webhooks to `site`, and return what the site needs to use it."""
	config = get_provider("meta")
	waba_id = get_waba_id(access_token, config.client_id, config.get_password("client_secret"))
	check_route(waba_id, site)

	phone_id = get_new_phone_id(waba_id, access_token)
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
	}


def get_waba_id(access_token: str, app_id: str, app_secret: str) -> str:
	"""The WABA the user picked in Meta's sign-in; the token's granular scopes name it."""
	token = call_graph("GET", "debug_token", f"{app_id}|{app_secret}", params={"input_token": access_token})
	for scope in token["data"].get("granular_scopes", []):
		if scope.get("scope") == "whatsapp_business_management" and scope.get("target_ids"):
			return scope["target_ids"][0]
	frappe.throw(_("Meta did not share a WhatsApp Business Account. Sign in again and pick one."))


def get_new_phone_id(waba_id: str, access_token: str) -> str:
	"""The number just signed in. Embedded Signup adds one number that is not on the Cloud API yet;
	an account with a single number is that number signed in again."""
	numbers = call_graph(
		"GET", f"{waba_id}/phone_numbers", access_token, params={"fields": "id,platform_type"}
	)["data"]
	new = [n for n in numbers if n.get("platform_type") == "NOT_APPLICABLE"] or numbers
	if not new:
		frappe.throw(
			_("This WhatsApp Business Account has no phone number. Add one at Meta, then try again.")
		)
	if len(new) > 1:
		# a wrong guess would change the two-step PIN of, and re-register, a number in use
		frappe.throw(
			_(
				"This WhatsApp Business Account has more than one phone number, and the one you added is not clear. Connect again and add a new number, or use an account with one number."
			)
		)
	return new[0]["id"]


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
		refuse(
			body,
			_(
				"The number's two-step verification PIN was changed. Connect again: that sets a new PIN and finishes the setup."
			),
		)


def check_route(waba_id: str, site: str) -> None:
	"""One site per WABA: another site's account is refused before Meta is changed for it."""
	refuse_other_site(frappe.db.get_value(ROUTE, waba_id, "site"), site)


def refuse_other_site(routed_site: str | None, site: str) -> None:
	if routed_site and routed_site != site:
		frappe.throw(
			_(
				"This WhatsApp Business Account is already connected to another Frappe Cloud site. Disconnect it there first."
			),
			title=_("Account in use"),
		)


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


def refuse(body: dict, note: str = "") -> None:
	# Graph's message says what failed and never holds a token or the PIN
	frappe.throw(
		" ".join(
			filter(None, (_("Meta refused the request: {0}").format(body["error"].get("message")), note))
		)
	)
