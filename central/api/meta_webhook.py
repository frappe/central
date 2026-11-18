import json

import frappe
from werkzeug.wrappers import Response

from central.integrations.oauth.meta_webhook import is_signed_by_meta, is_verify_token, relay


# nosemgrep: guest-whitelisted-method -- Meta calls it; GET checks the verify token, POST Meta's signature.
@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def handler() -> Response:
	"""Meta's webhook for Frappe Cloud's WhatsApp app. Meta needs plain text answers, so this
	returns a Response instead of Frappe's JSON."""
	if frappe.request.method == "GET":
		form = frappe.form_dict
		if form.get("hub.mode") == "subscribe" and form.get("hub.challenge"):
			if is_verify_token(form.get("hub.verify_token") or ""):
				return Response(form["hub.challenge"], status=200, mimetype="text/plain")
		return Response("Forbidden", status=403, mimetype="text/plain")

	raw = frappe.request.get_data()
	if not is_signed_by_meta(raw, frappe.get_request_header("X-Hub-Signature-256") or ""):
		return Response("Forbidden", status=403, mimetype="text/plain")
	# Meta waits only a few seconds, so the sends to sites run in background jobs
	relay(json.loads(raw))
	return Response("OK", status=200, mimetype="text/plain")
