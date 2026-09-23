from __future__ import annotations

import frappe
from frappe import _

from central.iam import can, resolve_team
from central.infrastructure.doctype.resource_action.resource_action import (
	ACTION_CAPABILITIES,
	PENDING_STATES,
)
from central.server_models import ActionStatus


def submit_command(
	action: str, team: str | None, resource_id: str | None, take_snapshot: bool = False
) -> ActionStatus:
	"""Authorize the specific operation and persist it before dispatch. Only a terminate can
	take a final snapshot first."""
	team = resolve_team(frappe.session.user, team)
	if action not in ACTION_CAPABILITIES or not can(frappe.session.user, team, ACTION_CAPABILITIES[action]):
		frappe.throw(_("You cannot perform this server action."), frappe.PermissionError)
	if take_snapshot and (action != "terminate" or not can(frappe.session.user, team, "server:snapshot")):
		frappe.throw(_("You cannot take a snapshot of this server."), frappe.PermissionError)
	if not isinstance(resource_id, str) or not resource_id:
		frappe.throw(_("Select a server."))

	server = frappe.get_doc("Virtual Machine", resource_id, for_update=True)
	if server.team != team:
		frappe.throw(_("This server belongs to another Team."), frappe.PermissionError)
	if not server.atlas_vm_id:
		frappe.throw(_("This server has no verified regional identity."))
	if action == "restart" and server.status != "Running":
		frappe.throw(_("Only a running server can be restarted."))

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
			"atlas_instance": server.cluster,
			"server": server.name,
			"resource_id": server.name,
			"remote_vm_id": server.atlas_vm_id,
			"title": server.title or server.name,
			"requested_by": frappe.session.user,
			"correlation_id": frappe.generate_hash(length=32),
			"take_snapshot": int(take_snapshot),
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


def retry(name: str) -> ActionStatus:
	"""Re-drive one action. The record owns permission and what is safe to send again."""
	return frappe.get_doc("Resource Action", name).retry()
