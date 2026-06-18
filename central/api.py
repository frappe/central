from __future__ import annotations

import frappe
from frappe import _

from central.iam import can, get_effective_permissions, get_fc_teams_claim


def _assert_can_inspect(user: str) -> None:
	if frappe.session.user != user and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only System Manager can inspect another user's permissions"), frappe.PermissionError)


@frappe.whitelist(methods=["GET"])
def fc_teams(user: str | None = None) -> dict:
	user = user or frappe.session.user
	frappe.only_for(("System Manager", "Central User"))
	_assert_can_inspect(user)
	return get_fc_teams_claim(user)


@frappe.whitelist(methods=["GET"])
def effective_permissions(user: str, team: str | None = None) -> dict:
	frappe.only_for(("System Manager", "Central User"))
	_assert_can_inspect(user)
	return get_effective_permissions(user, team)


@frappe.whitelist(methods=["GET"])
def check_capability(user: str, team: str, capability: str) -> dict:
	frappe.only_for(("System Manager", "Central User"))
	_assert_can_inspect(user)
	return {
		"user": user,
		"team": team,
		"capability": capability,
		"allowed": can(user, team, capability),
	}


# --- Atlas-facing inbound contract (spec/16-central.md "The wire contract") --
# Atlas is the client: it pings, registers, fetches catalogs, and reports events.
# Authenticated by the calling Atlas's Frappe token; `register` assigns the
# `atlas_id` that `event` then routes on.


@frappe.whitelist(methods=["GET"])
def ping() -> dict:
	"""Reachability + auth check for a registering Atlas."""
	return {"label": frappe.local.site}


@frappe.whitelist(methods=["POST"])
def register(**kwargs) -> dict:
	"""Register a regional Atlas: match its (operator-created) Atlas Instance by
	region and assign a stable `atlas_id`, which Atlas stamps on every event so we
	can route them to this cluster."""
	region = frappe._dict(kwargs).region
	if not region:
		frappe.throw(_("region is required to register."), frappe.ValidationError)
	name = frappe.db.get_value("Atlas Instance", {"region": region})
	if not name:
		frappe.throw(_("No Atlas Instance configured for region {0}.").format(region), frappe.DoesNotExistError)
	instance = frappe.get_doc("Atlas Instance", name)
	if not instance.atlas_id:
		instance.atlas_id = frappe.generate_hash(length=12)
		# System write: Atlas Instance is operator-managed (not writable by the
		# authenticated service caller), and stamping the id is part of registration.
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


@frappe.whitelist(methods=["POST"])
def event(**kwargs) -> dict:
	"""Webhook sink for Atlas lifecycle events (spec/16-central.md § Event reporting).

	Atlas authenticates with its Frappe token; `ingest_event` then verifies the
	`atlas_id` is one we know before touching the mirror. Body: `atlas_id`, `type`,
	`payload`, `occurred_at`.
	"""
	from central.atlas import ingest_event

	data = frappe._dict(kwargs)
	payload = frappe.parse_json(data.payload) if isinstance(data.payload, str) else (data.payload or {})
	return ingest_event(data.atlas_id, data.type, payload, data.occurred_at)
