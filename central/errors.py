"""User-facing error envelopes for server-flow actions.

A failed action must tell the user what happened and what to do about it — never a
FrappeException or a raw traceback. Every server-action failure is shaped into a small
envelope ({code, title, message, remediation, retriable}) built from `ERROR_CATALOG`,
and carried to the client on the message it raises (Frappe serializes each message-log
entry, extra keys included, into `_server_messages`). The stable `code` is what the UI
switches on; `message`/`remediation` are the words a person reads (see the Wix "write
better error messages" guidance: plain language, cause, reassurance, next step).

Wire this at the two ends of the Server flow: `throw_action_error` where Central raises a
known failure, and the `@server_action` decorator on the whitelisted endpoints so nothing
— not even an unexpected bug — reaches the user as a bare exception.
"""

from __future__ import annotations

import functools

import frappe
from frappe import _

# The message key the envelope rides on inside each _server_messages entry.
ENVELOPE_KEY = "server_action_error"


class ServerActionError(frappe.ValidationError):
	"""A server-flow failure already shaped into a user-facing envelope."""


# code -> user-facing copy. Templates are formatted with the call's context (action,
# region, resource_id, field); a missing placeholder renders empty rather than crashing
# the error path. `message` may be overridden at the call site (e.g. Atlas's own sentence).
ERROR_CATALOG: dict[str, dict] = {
	"PERMISSION_DENIED": {
		"title": "You don't have access",
		"message": "Your role on this team isn't allowed to {action} servers.",
		"remediation": "Ask a team admin to grant you server access, or switch to a team where you have it.",
		"retriable": False,
	},
	"INPUT_REQUIRED": {
		"title": "Missing information",
		"message": "{field} is required to continue.",
		"remediation": "",
		"retriable": False,
	},
	"SERVER_NOT_FOUND": {
		"title": "Server not found",
		"message": "We couldn't find the server '{resource_id}' on this team.",
		"remediation": "It may have been terminated, or it belongs to another team. Refresh your server list and try again.",
		"retriable": False,
	},
	"SERVER_BUSY_RESIZING": {
		"title": "Server is resizing",
		"message": "This server is resizing right now. You can {action} it as soon as the resize finishes.",
		"remediation": "",
		"retriable": True,
	},
	"REGION_UNAVAILABLE": {
		"title": "Region isn't responding",
		"message": "We couldn't {action} — the region ({region}) isn't responding right now, and nothing was changed.",
		"remediation": "This is usually temporary. Please try again in a moment; if it keeps happening, contact support.",
		"retriable": True,
	},
	"ATLAS_REJECTED": {
		"title": "Couldn't {action}",
		"message": "The region couldn't complete this request.",
		"remediation": "",
		"retriable": False,
	},
	"VALIDATION_ERROR": {
		"title": "Please check and try again",
		"message": "We couldn't complete that action.",
		"remediation": "",
		"retriable": False,
	},
	"UNEXPECTED": {
		"title": "Something went wrong on our end",
		"message": "We hit an unexpected problem completing that action, and nothing was changed.",
		"remediation": "Please try again in a moment. If it keeps happening, contact support so we can look into it.",
		"retriable": True,
	},
}


class _SafeContext(dict):
	"""format_map source that renders a missing placeholder as empty, so building an
	error message can never itself raise."""

	def __missing__(self, key: str) -> str:
		return ""


def build_envelope(code: str, *, message: str | None = None, remediation: str | None = None, **context) -> dict:
	"""Shape one catalog entry into an envelope, filling templates from `context`.
	`message`/`remediation` override the catalog copy when the caller has better words
	(e.g. the region's own error sentence)."""
	entry = ERROR_CATALOG.get(code, ERROR_CATALOG["UNEXPECTED"])
	source = _SafeContext(context)

	return {
		"code": code if code in ERROR_CATALOG else "UNEXPECTED",
		"title": _(entry["title"]).format_map(source),
		"message": (message or _(entry["message"])).format_map(source),
		"remediation": (remediation if remediation is not None else _(entry["remediation"])).format_map(source),
		"retriable": entry["retriable"],
	}


def throw_action_error(code: str, *, exc: type[Exception] = ServerActionError, **context) -> None:
	"""Raise a known server-flow failure as a clean, structured error. Pass `exc` to keep
	the right HTTP status (e.g. frappe.PermissionError for 403); pass `message`/`remediation`
	in `context` to override the catalog copy."""
	envelope = build_envelope(code, **context)
	_carry(envelope)

	error = exc(envelope["message"])
	error.envelope = envelope
	raise error


def to_error_response(exc: Exception) -> dict:
	"""Shape an already-raised exception into an envelope. A message the user was meant to
	see (any frappe exception) is preserved verbatim; a genuinely unexpected error is logged
	for operators and shown a generic, honest message instead of its internals."""
	if getattr(exc, "envelope", None):
		return exc.envelope

	if isinstance(exc, frappe.PermissionError):
		return build_envelope("PERMISSION_DENIED", message=str(exc) or None)

	if isinstance(exc, frappe.DoesNotExistError):
		return build_envelope("SERVER_NOT_FOUND", message=str(exc) or None)

	if isinstance(exc, frappe.ValidationError):
		return build_envelope("VALIDATION_ERROR", message=str(exc) or None)

	frappe.log_error(title="Unexpected server-action error", message=frappe.get_traceback())
	return build_envelope("UNEXPECTED")


def server_action(func):
	"""Guarantee a whitelisted server action fails as a clean envelope, never a bare
	exception. An error already shaped by `throw_action_error` passes through untouched;
	anything else is converted, preserving the user's message and the exception's status."""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		try:
			return func(*args, **kwargs)
		except Exception as exc:
			if getattr(exc, "envelope", None):
				raise

			envelope = to_error_response(exc)
			_reraise_with_envelope(exc, envelope)

	return wrapper


def _reraise_with_envelope(exc: Exception, envelope: dict) -> None:
	"""Attach the envelope to what the client receives. A frappe exception already logged
	its message, so enrich that entry and keep the original type (and status); anything
	else gets a fresh message and is re-raised as a ServerActionError."""
	if isinstance(exc, (frappe.ValidationError, frappe.PermissionError)) and frappe.message_log:
		frappe.message_log[-1][ENVELOPE_KEY] = envelope
		exc.envelope = envelope
		raise exc

	_carry(envelope)

	error = ServerActionError(envelope["message"])
	error.envelope = envelope
	raise error from exc


def _carry(envelope: dict) -> None:
	"""Append the message-log entry that carries this envelope to the client."""
	frappe.message_log.append(
		frappe._dict(
			message=envelope["message"],
			title=envelope["title"],
			indicator="red",
			raise_exception=1,
			**{ENVELOPE_KEY: envelope},
		)
	)
