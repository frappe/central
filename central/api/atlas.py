# Central API endpoints for Atlas. Atlas is the client and it will send webhooks to "event" endpoint.
# Rest of the endpoints are for Atlas to register and check health.

from __future__ import annotations

import frappe
from frappe import _

from central.integrations.atlas import ingest_event


@frappe.whitelist(methods=["POST"])
def event(**kwargs) -> dict:
	"""
	Webhook sink for Atlas lifecycle events. Atlas authenticates with its Frappe
	token; ingest_event verifies the sender, then queues the mirror update so Atlas
	gets a fast ack. Body: `atlas_id`, `type`, `payload`, `occurred_at`.

	"""
	data = frappe._dict(kwargs)
	payload = frappe.parse_json(data.payload) if isinstance(data.payload, str) else (data.payload or {})

	return ingest_event(data.atlas_id, data.type, payload, data.occurred_at)


@frappe.whitelist(methods=["POST"])
def register(**kwargs) -> dict:
	"""
	Register a regional Atlas: match its (operator-created) Atlas Instance by
	region and assign a stable `atlas_id`, which Atlas stamps on every event so we
	can route them to this cluster.
	"""
	region = frappe._dict(kwargs).region
	if not region:
		frappe.throw(_("Region is required to register on Central."), frappe.ValidationError)

	name = frappe.db.get_value("Atlas Instance", {"region": region})
	if not name:
		frappe.throw(_("No Atlas Instance configured for region {0}.").format(region), frappe.DoesNotExistError)

	instance = frappe.get_doc("Atlas Instance", name)
	if not instance.atlas_id:
		instance.atlas_id = frappe.generate_hash(length=12)
		# Atlas Instance is operator-managed (not writable by the authenticated
		# service caller); stamping the id is part of registration.
		instance.save(ignore_permissions=True)

	return {"atlas_id": instance.atlas_id, "label": frappe.local.site}


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
