# Central API endpoints for Atlas. Atlas is the client and it will send webhooks to "event" endpoint.
# Rest of the endpoints are for Atlas to register and check health.

from __future__ import annotations

import frappe
from frappe import _

from central.integrations.atlas import ingest_event


@frappe.whitelist(methods=["POST"])
def event(**kwargs) -> dict:
	"""
	Webhook sink for Atlas lifecycle events. Atlas authenticates with its scoped
	Central service-user token; ingest_event resolves the sender from that session,
	then queues the mirror update so Atlas gets a fast ack. Body: `type`, `payload`,
	`occurred_at`.

	"""
	data = frappe._dict(kwargs)
	payload = frappe.parse_json(data.payload) if isinstance(data.payload, str) else (data.payload or {})

	return ingest_event(data.type, payload, data.occurred_at)


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
