"""Customer-safe errors and operator diagnostics for console APIs.

A failed action must tell the user what happened and what to do about it — never a
FrappeException or a raw traceback. Every server-action failure is shaped into a small
envelope ({code, title, message, remediation, retriable}) built from `ERROR_CATALOG`,
and carried to the client on the message it raises (Frappe serializes each message-log
entry, extra keys included, into `_server_messages`). The stable `code` is what the UI
switches on; `message`/`remediation` are the words a person reads (see the Wix "write
better error messages" guidance: plain language, cause, reassurance, next step).

Wire this at the two ends of the Server flow: `throw_action_error` where Central raises a
known failure, and the `@handle_resource_operation` decorator on the whitelisted endpoints so
nothing, including an unexpected bug, reaches the user as a bare exception.
"""

from __future__ import annotations

import functools

import frappe
from frappe import _

# The message key the envelope rides on inside each _server_messages entry.
ENVELOPE_KEY = "action_error"


class ResourceActionError(frappe.ValidationError):
	"""A server-flow failure already shaped into a user-facing envelope."""


class AtlasConnectionError(frappe.ValidationError):
	"""A regional read or authentication/configuration check failed."""


class AtlasRejected(AtlasConnectionError):
	"""Atlas explicitly rejected a mutation before accepting it."""


class AtlasResourceGone(AtlasConnectionError):
	"""A correctly scoped regional resource was not found."""


class AtlasRequestUncertain(AtlasConnectionError):
	"""A remote mutation may have succeeded without a confirmed response."""


class CargoConnectionError(frappe.ValidationError):
	"""A regional Cargo health check or webhook configuration call failed."""


# code -> user-facing copy. Templates are formatted with the call's context (action,
# region, resource_id, field); a missing placeholder renders empty rather than crashing
# the error path. `message` may be overridden when Central owns customer-safe copy.
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
		"title": "This region is temporarily unavailable",
		"message": "We couldn't reach the selected region.",
		"remediation": "Try again in a few minutes. If the problem continues, contact support.",
		"retriable": True,
	},
	"ATLAS_REJECTED": {
		"title": "This request couldn't be completed",
		"message": "The selected region couldn't complete this request.",
		"remediation": "Review your selections and try again. If the problem continues, contact support.",
		"retriable": False,
	},
	"RESOURCE_GONE": {
		"title": "This server is no longer available",
		"message": "The server may already have been removed.",
		"remediation": "Refresh your server list to see the current state.",
		"retriable": False,
	},
	"ACTION_FAILED": {
		"title": "The {action} didn't complete",
		"message": "Your server reported a failure while trying to {action}, and it's now in a failed state.",
		"remediation": "Review the existing server and contact support before submitting another operation.",
		"retriable": False,
	},
	"ACTION_TIMED_OUT": {
		"title": "The {action} is taking too long",
		"message": "We haven't heard back that the {action} finished. It may still complete on its own.",
		"remediation": "Refresh your server list in a few minutes. If it still looks stuck, contact support.",
		"retriable": False,
	},
	"CREATE_NOT_ACCEPTED": {
		"title": "The server wasn't created",
		"message": "The selected region did not accept the request. No server was created.",
		"remediation": "Try again, or select another region if the problem continues.",
		"retriable": True,
	},
	"SNAPSHOT_FAILED": {
		"title": "The final snapshot didn't complete",
		"message": "The snapshot failed, so the server was not removed. The server is stopped.",
		"remediation": "Start the server again, or terminate it without a snapshot.",
		"retriable": True,
	},
	"OUTCOME_UNKNOWN": {
		"title": "We're still confirming this request",
		"message": "We couldn't confirm whether the selected region accepted it.",
		"remediation": "We'll keep checking. Don't submit the request again.",
		"retriable": False,
	},
	"REFRESH_FAILED": {
		"title": "Progress isn't available yet",
		"message": "Your request was accepted, but we couldn't load its latest status.",
		"remediation": "We'll check again automatically. Don't submit another request.",
		"retriable": False,
	},
	"FINALIZATION_FAILED": {
		"title": "Setup needs support",
		"message": "The selected region accepted the request, but setup did not finish.",
		"remediation": "Don't submit another request. Contact support with this action ID.",
		"retriable": False,
	},
	"VALIDATION_ERROR": {
		"title": "Please check and try again",
		"message": "We couldn't complete that action.",
		"remediation": "",
		"retriable": False,
	},
	"UNEXPECTED": {
		"title": "We couldn't complete that",
		"message": "Something went wrong while we were processing your request.",
		"remediation": "Check its status before trying again. If the result is unclear, contact support.",
		"retriable": False,
	},
}


class _SafeContext(dict):
	"""format_map source that renders a missing placeholder as empty, so building an
	error message can never itself raise."""

	def __missing__(self, key: str) -> str:
		return ""


def build_envelope(
	code: str, *, message: str | None = None, remediation: str | None = None, **context
) -> dict:
	"""Shape one catalog entry into an envelope, filling templates from `context`.
	`message`/`remediation` override the catalog copy when the caller has better words
	(e.g. the region's own error sentence)."""
	entry = ERROR_CATALOG.get(code, ERROR_CATALOG["UNEXPECTED"])
	source = _SafeContext(context)

	return {
		"code": code if code in ERROR_CATALOG else "UNEXPECTED",
		"title": _(entry["title"]).format_map(source),
		"message": message if message is not None else _(entry["message"]).format_map(source),
		"remediation": remediation if remediation is not None else _(entry["remediation"]).format_map(source),
		"retriable": entry["retriable"],
	}


def throw_action_error(code: str, *, exc: type[Exception] = ResourceActionError, **context) -> None:
	"""Raise a known server-flow failure as a clean, structured error. Pass `exc` to keep
	the right HTTP status (e.g. frappe.PermissionError for 403); pass `message`/`remediation`
	in `context` to override the catalog copy."""
	envelope = build_envelope(code, **context)
	_carry(envelope)

	error = exc(envelope["message"])
	error.envelope = envelope
	raise error


def to_error_response(exc: Exception) -> dict:
	"""Shape an already-raised exception into a customer-safe envelope."""
	if getattr(exc, "envelope", None):
		return exc.envelope

	if isinstance(exc, AtlasRequestUncertain):
		return build_envelope("OUTCOME_UNKNOWN")
	if isinstance(exc, AtlasResourceGone):
		return build_envelope("RESOURCE_GONE")
	if isinstance(exc, AtlasRejected):
		return build_envelope("ATLAS_REJECTED")
	if isinstance(exc, AtlasConnectionError):
		return build_envelope("REGION_UNAVAILABLE")

	if isinstance(exc, frappe.PermissionError):
		return build_envelope("PERMISSION_DENIED", message=str(exc) or None)

	if isinstance(exc, frappe.DoesNotExistError):
		return build_envelope("SERVER_NOT_FOUND", message=str(exc) or None)

	if isinstance(exc, frappe.ValidationError):
		return build_envelope("VALIDATION_ERROR", message=str(exc) or None)

	return build_envelope("UNEXPECTED")


def handle_resource_operation(func):
	"""Return customer-safe errors from a resource endpoint."""

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
	else gets a fresh message and is re-raised as a ResourceActionError."""
	if isinstance(exc, (frappe.ValidationError, frappe.PermissionError)) and frappe.message_log:
		frappe.message_log[-1]["message"] = _display_message(envelope)
		frappe.message_log[-1][ENVELOPE_KEY] = envelope
		exc.envelope = envelope
		raise exc

	_carry(envelope)

	error = ResourceActionError(envelope["message"])
	error.envelope = envelope
	raise error from exc


def _display_message(envelope: dict) -> str:
	"""What the user reads: what happened, then how to resolve it. frappe-ui surfaces only
	this line and drops the structured envelope, so the remediation has to ride here too."""
	remediation = envelope.get("remediation")
	return f"{envelope['message']} {remediation}".strip() if remediation else envelope["message"]


def _carry(envelope: dict) -> None:
	"""Append the message-log entry that carries this envelope to the client."""
	frappe.message_log.append(
		frappe._dict(
			message=_display_message(envelope),
			title=envelope["title"],
			indicator="red",
			raise_exception=1,
			**{ENVELOPE_KEY: envelope},
		)
	)
