import hashlib
import hmac

import frappe
from frappe.integrations.doctype.webhook.webhook import get_next_retry, log_request, send_webhook_request
from frappe.utils.password import get_decrypted_password

from central.integrations.oauth.meta import ROUTE

WEBHOOK = "Meta to site"
SITE_HANDLER_PATH = "/api/method/whatsapp.whatsapp.webhook.handler"
CENTRAL_SIGNATURE_HEADER = "X-Frappe-Central-Signature"


def is_verify_token(token: str) -> bool:
	"""Meta's subscribe check sends back the verify token set in Central's site config."""
	expected = frappe.conf.get("meta_webhook_verify_token")
	return bool(expected) and hmac.compare_digest(token.encode(), expected.encode())


def is_signed_by_meta(raw: bytes, signature: str) -> bool:
	"""Meta signs each webhook body with the app secret: `sha256=<hex HMAC>`."""
	secret = frappe.conf.get("meta_app_secret")
	if not (secret and signature.startswith("sha256=")):
		return False
	digest = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
	return hmac.compare_digest(digest.encode(), signature.removeprefix("sha256=").encode())


def relay(body: dict) -> None:
	"""Queue one delivery per routed WhatsApp Business Account (WABA) in Meta's batch.
	The site checks one WABA's secret per request, so a mixed batch is split per WABA."""
	entries_by_waba = {}
	for entry in body.get("entry") or []:
		if isinstance(entry, dict) and entry.get("id"):
			entries_by_waba.setdefault(str(entry["id"]), []).append(entry)
	if not entries_by_waba:
		return

	for waba_id in frappe.get_all(ROUTE, {"name": ["in", list(entries_by_waba)]}, pluck="name"):
		frappe.enqueue(
			deliver,
			waba_id=waba_id,
			body={**body, "entry": entries_by_waba[waba_id]},
			enqueue_after_commit=True,
		)


def deliver(waba_id: str, body: dict) -> None:
	"""First try to the WABA's site. A failed try is a Failed row on the "Meta to site" Webhook,
	and Frappe's retry job sends its URL, headers and body again."""
	site = frappe.db.get_value(ROUTE, waba_id, "site")
	if not site:  # disconnected after Meta's call
		return
	secret = get_decrypted_password(ROUTE, waba_id, "webhook_secret")
	# send_webhook_request sends frappe.as_json(body); a retry sends the same text, so this signature holds
	digest = hmac.new(secret.encode(), frappe.as_json(body).encode(), hashlib.sha256).hexdigest()
	headers = {"Content-Type": "application/json", CENTRAL_SIGNATURE_HEADER: f"sha256={digest}"}
	url = f"https://{site}{SITE_HANDLER_PATH}"

	response = None
	try:
		response = send_webhook_request(
			"POST", url, headers, body, frappe.db.get_value("Webhook", WEBHOOK, "timeout")
		)
		response.raise_for_status()
		log_request(WEBHOOK, "Site", site, url, headers, body, response, status="Delivered")
	except Exception:
		log_request(
			WEBHOOK, "Site", site, url, headers, body, response, status="Failed", next_retry=get_next_retry(1)
		)


def ensure_meta_webhook() -> None:
	"""Seed the Webhook the relay logs its tries against. Its condition is never true, so Frappe
	never fires it for a Site; only the retry job uses it, for up to 5 more tries."""
	if frappe.db.exists("Webhook", WEBHOOK):
		return
	# Runs from the install, migrate and test hooks, which have no signed-in user
	frappe.get_doc(
		{
			"doctype": "Webhook",
			"__newname": WEBHOOK,
			"webhook_doctype": "Site",
			"webhook_docevent": "on_update",
			"condition": "False",
			"request_url": f"https://{{{{ doc.name }}}}{SITE_HANDLER_PATH}",
			"is_dynamic_url": 1,
			"request_structure": "JSON",
			"webhook_json": "{}",
			"max_retries": 5,
			"enabled": 1,
		}
	).insert(ignore_permissions=True)
