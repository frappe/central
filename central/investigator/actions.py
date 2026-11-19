from __future__ import annotations

from typing import Annotated

import frappe
from frappe import _
from frappe.flow import ToolContext, tool

from central.investigator.access import (
	READ_WRITE_SECONDS,
	enable_read_write,
	refuse_destruction,
	require_read_write,
)
from central.investigator.scrub import scrub_value


def _confirm_switch(arguments: dict) -> str:
	return _("Switch this session to read-write for one hour? Reason: {0}").format(arguments.get("reason"))


def _confirm_desk_action(arguments: dict) -> str:
	return _("Run {0} on {1} {2} with {3}?").format(
		arguments.get("method"), arguments.get("doctype"), arguments.get("name"), arguments.get("args") or {}
	)


def _confirm_central_api(arguments: dict) -> str:
	return _("Call {0} with {1}?").format(arguments.get("method"), arguments.get("args") or {})


@tool(requires_confirmation=True, confirm_prompt=_confirm_switch)
def switch_to_read_write(
	reason: Annotated[str, "The change you want to make, and the evidence for it."],
	*,
	ctx: ToolContext,
) -> dict:
	"""Switch this session to read-write for one hour. Call it only after the user says yes.

	The session starts read-only. After the switch, each change still asks the user for approval.
	"""
	enable_read_write(ctx)
	return {"mode": "read-write", "expires_in_minutes": READ_WRITE_SECONDS // 60}


@tool(requires_confirmation=True, confirm_prompt=_confirm_desk_action)
def run_desk_action(
	doctype: Annotated[str, "DocType, such as Virtual Machine, Site, or Resource Action."],
	name: Annotated[str, "Document name."],
	method: Annotated[str, "Document method that a Desk button calls, such as retry or sync_state."],
	args: Annotated[dict | None, 'Method arguments, such as {"days": 7}.'] = None,
	*,
	ctx: ToolContext,
) -> dict | list | str:
	"""Run the action of a Desk button on one document, as the user. Needs a read-write session."""
	require_read_write(ctx)
	refuse_destruction(method)
	document = frappe.get_doc(doctype, name)
	document.check_permission("write")

	action = getattr(document, method, None)
	if not callable(action):
		frappe.throw(_("{0} has no action {1}.").format(doctype, method))
	frappe.is_whitelisted(getattr(action, "__func__", action))

	return scrub_value(action(**(args or {}))) or {"status": "done"}


@tool(requires_confirmation=True, confirm_prompt=_confirm_central_api)
def call_central_api(
	method: Annotated[str, "Central API method, such as central.api.servers.restart_server."],
	args: Annotated[
		dict | None, 'Method arguments, such as {"team": "TEAM-00001", "resource_id": "..."}.'
	] = None,
	*,
	ctx: ToolContext,
) -> dict | list | str:
	"""Call a central.api method, as the console does, as the user. Needs a read-write session.

	Examples: central.api.servers.start_server, stop_server, restart_server, resize_server, and
	central.api.snapshots.take_snapshot.
	"""
	require_read_write(ctx)
	if not method.startswith("central.api."):
		frappe.throw(_("Only central.api methods can be called."), frappe.PermissionError)
	refuse_destruction(method)

	function = frappe.get_attr(method)
	frappe.is_whitelisted(function)

	return scrub_value(function(**(args or {}))) or {"status": "done"}
