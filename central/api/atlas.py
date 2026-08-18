# Central API endpoints for Atlas. Atlas is the client and it will send webhooks to "event" endpoint.
# Rest of the endpoints are for Atlas to register and check health.

from __future__ import annotations

import frappe
from frappe import _

from central.integrations.atlas import ingest_event, verify_atlas_webhook


@frappe.whitelist(allow_guest=True, methods=["POST"])
@verify_atlas_webhook
def event() -> dict:
	"""Webhook sink for Atlas lifecycle events (spec/16-central.md). The decorator is the
	only gate — nothing keyed on payload content runs until the HMAC verifies."""
	context = frappe.local.atlas_webhook
	body = context.raw.decode() if isinstance(context.raw, bytes) else context.raw
	data = frappe.parse_json(body) if body else None
	if not isinstance(data, dict):
		# Signed but not an object (array, null, empty) — ack like an unknown event type.
		data = frappe._dict()
	payload = frappe.parse_json(data.payload) if isinstance(data.payload, str) else (data.payload or {})

	return ingest_event(
		context.cluster,
		data.type,
		payload,
		data.occurred_at,
		data.event_id,
		raw_body=context.raw,
		signature=context.signature,
		signature_timestamp=context.timestamp,
	)


# --- Inbound Atlas HTTP endpoints -------------------------------------------
# register/sizes/images/ping have no internal caller by design — they are the
# contract an Atlas deployment calls into Central. `grep` showing zero callers in
# this repo is expected; deleting one turns a live Atlas call into a 404. (Cannot
# verify against the Atlas repo from here — kept per plan decision.)


@frappe.whitelist(methods=["POST"])
def register(**kwargs) -> dict:
	"""Retired. Registration is Central-initiated now (central/spec/TUNNEL.md): the
	operator runs Register on the Atlas Instance, which drives the tunnel handshake
	(provision_tunnel / confirm_tunnel) and mints the scoped service user from Central's
	side. This inbound endpoint no longer registers anything; it stays only to give an old
	Atlas build a clear signal instead of a 404."""
	frappe.throw(
		_("Atlas-initiated register is retired; registration is Central-initiated."),
		frappe.ValidationError,
	)


@frappe.whitelist(methods=["GET"])
def sizes() -> dict:
	"""VM size catalog Central declares for Atlas. Empty until catalog management
	lands — wired so Atlas's Fetch Sizes is a clean no-op, not an error."""
	return {"sizes": []}


@frappe.whitelist(methods=["GET"])
def images() -> dict:
	"""Expected bench images Central declares for Atlas. Empty for now (see sizes)."""
	return {"images": []}


@frappe.whitelist(methods=["GET"])
def ping() -> dict:
	"""Reachability + auth check for a registering Atlas."""
	return {"label": frappe.local.site}
