from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.flow import ToolContext

from central.iam import user_has_operator_bypass

READ_WRITE_SECONDS = 3600
# The agent never terminates or destroys a resource. The operator does it in Desk.
DESTRUCTIVE = re.compile(
	r"terminat|delet|destroy|drop|purge|uninstall|reinstall|restore|trash|wipe|end_trial", re.IGNORECASE
)
# These return a login, a console, or a secret, which must not reach the agent.
CREDENTIAL = re.compile(r"login|console|administrator|password|token|secret|credential", re.IGNORECASE)


def require_operator(ctx: ToolContext) -> None:
	if not user_has_operator_bypass(ctx.user):
		frappe.throw(_("Only an operator can use the Central Investigator."), frappe.PermissionError)


def enable_read_write(ctx: ToolContext) -> None:
	"""Let this session make changes for one hour."""
	require_operator(ctx)
	_refuse_auto_approve(ctx)
	frappe.cache.set_value(read_write_key(ctx), ctx.user, expires_in_sec=READ_WRITE_SECONDS)


def require_read_write(ctx: ToolContext) -> None:
	"""Rules, in order:
	1. The user is an operator.
	2. The session does not approve its own tool calls.
	3. The same user switched this session to read-write in the last hour.
	"""
	require_operator(ctx)
	_refuse_auto_approve(ctx)
	if frappe.cache.get_value(read_write_key(ctx)) != ctx.user:
		frappe.throw(
			_("This session is read-only. Ask the user to switch it to read-write first."),
			frappe.PermissionError,
		)


def refuse_destruction(action: str) -> None:
	if DESTRUCTIVE.search(action):
		frappe.throw(
			_("The agent does not terminate or destroy resources. Do {0} in Desk.").format(action),
			frappe.PermissionError,
		)
	if CREDENTIAL.search(action):
		frappe.throw(
			_("{0} returns a credential, so the agent cannot run it.").format(action), frappe.PermissionError
		)


def _refuse_auto_approve(ctx: ToolContext) -> None:
	# An auto-approved session makes changes without a person, so it stays read-only.
	if frappe.db.get_value("Flow Session", ctx.session_id, "auto_approve"):
		frappe.throw(_("A session that approves its own tool calls stays read-only."), frappe.PermissionError)


def read_write_key(ctx: ToolContext) -> str:
	return f"central:investigator:read-write:{ctx.session_id}"
