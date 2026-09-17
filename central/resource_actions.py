from __future__ import annotations

import frappe
from frappe import _

from central.central.doctype.resource_action.resource_action import PENDING_STATES
from central.iam import can, resolve_team
from central.server_models import ActionStatus

CAPABILITY = {"start": "server:power", "stop": "server:power", "terminate": "server:terminate"}


def submit_command(action: str, team: str | None, resource_id: str | None) -> ActionStatus:
	"""Authorize the specific operation and persist it before dispatch."""
	team = resolve_team(frappe.session.user, team)
	if action not in CAPABILITY or not can(frappe.session.user, team, CAPABILITY[action]):
		frappe.throw(_("You cannot perform this server action."), frappe.PermissionError)
	if not isinstance(resource_id, str) or not resource_id:
		frappe.throw(_("Select a server."))

	asset = frappe.get_doc("Asset", resource_id, for_update=True)
	if asset.team != team:
		frappe.throw(_("This server belongs to another Team."), frappe.PermissionError)
	if not asset.atlas_vm_id:
		frappe.throw(_("This server has no verified regional identity."))
	if asset.resize_in_progress:
		frappe.throw(_("Wait for the server resize to finish."))

	pending = frappe.db.get_value(
		"Resource Action",
		{
			"team": team,
			"resource_id": resource_id,
			"status": ["in", PENDING_STATES],
		},
	)
	if pending:
		existing = frappe.get_doc("Resource Action", pending)
		if existing.action == action:
			return existing.customer_status()
		frappe.throw(_("Another action is still pending for this server."))

	document = frappe.get_doc(
		{
			"doctype": "Resource Action",
			"resource_type": "Server",
			"action": action,
			"team": team,
			"atlas_instance": asset.cluster,
			"asset": asset.name,
			"resource_id": asset.name,
			"remote_vm_id": asset.atlas_vm_id,
			"title": asset.title or asset.name,
			"requested_by": frappe.session.user,
			"correlation_id": frappe.generate_hash(length=32),
			"status": "Queued",
		}
	)
	# The capability and owning Team are checked above; customers cannot write action state.
	document.insert(ignore_permissions=True)
	return document.customer_status()


def get_status(name: str) -> ActionStatus:
	document = frappe.get_doc("Resource Action", name)
	document.check_permission("read")
	return document.customer_status()
