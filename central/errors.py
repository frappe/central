"""User-facing error envelopes for server-flow actions.

A failed action must tell the user what happened and what to do about it — never a
FrappeException or a raw traceback. Every server-action failure is shaped into a small
envelope ({code, title, message, remediation, retriable}) built from `ERROR_CATALOG`,
and carried to the client on the message it raises (Frappe serializes each message-log
entry, extra keys included, into `_server_messages`). The stable `code` is what the UI
switches on; `message`/`remediation` are the words a person reads (see the Wix "write
better error messages" guidance: plain language, cause, reassurance, next step).

Wire this at the two ends of the Server flow: `throw_action_error` where Central raises a
known failure, and the `@resource_action` decorator on the whitelisted endpoints so nothing
— not even an unexpected bug — reaches the user as a bare exception.
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
		"message": "The region is not responding. Central could not refresh this resource.",
		"remediation": "This is usually temporary. Please try again in a moment; if it keeps happening, contact support.",
		"retriable": True,
	},
	"ATLAS_REJECTED": {
		"title": "Couldn't {action}",
		"message": "The region couldn't complete this request.",
		"remediation": "",
		"retriable": False,
	},
	"RESOURCE_GONE": {
		"title": "No longer exists",
		"message": "This server no longer exists in its region — it may already have been removed.",
		"remediation": "Refresh your list to see the current state.",
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
		"title": "Couldn't {action}",
		"message": "The region did not take this request, and no server was built.",
		"remediation": "",
		"retriable": True,
	},
	"OUTCOME_UNKNOWN": {
		"title": "The operation result is not confirmed",
		"message": "Atlas may have accepted this operation, but Central did not receive a valid confirmation.",
		"remediation": "Central is checking the region for it and will follow up on its own.",
		"retriable": False,
	},
	"REFRESH_FAILED": {
		"title": "Progress could not be refreshed",
		"message": "The operation was accepted. Central could not read its current state.",
		"remediation": "Central will retry the status check. Do not create another server.",
		"retriable": False,
	},
	"FINALIZATION_FAILED": {
		"title": "Central could not finish the local update",
		"message": "Atlas accepted this operation, but Central could not finish updating its records.",
		"remediation": "Contact support with this action ID. The recorded VM will be checked without creating another.",
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
		"message": "Central encountered an unexpected problem processing this action.",
		"remediation": "Check the action status before trying again. Contact support if the result is unclear.",
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
	"""Shape an already-raised exception into an envelope. A message the user was meant to
	see (any frappe exception) is preserved verbatim; a genuinely unexpected error is logged
	for operators and shown a generic, honest message instead of its internals."""
	if getattr(exc, "envelope", None):
		return exc.envelope

	if isinstance(exc, AtlasRequestUncertain):
		return build_envelope("OUTCOME_UNKNOWN")
	if isinstance(exc, AtlasResourceGone):
		return build_envelope("RESOURCE_GONE")
	if isinstance(exc, AtlasRejected):
		return build_envelope("ATLAS_REJECTED", message=str(exc))
	if isinstance(exc, AtlasConnectionError):
		return build_envelope("REGION_UNAVAILABLE", message=str(exc))

	if isinstance(exc, frappe.PermissionError):
		return build_envelope("PERMISSION_DENIED", message=str(exc) or None)

	if isinstance(exc, frappe.DoesNotExistError):
		return build_envelope("SERVER_NOT_FOUND", message=str(exc) or None)

	if isinstance(exc, frappe.ValidationError):
		return build_envelope("VALIDATION_ERROR", message=str(exc) or None)

	frappe.log_error(title="Unexpected server-action error", message=frappe.get_traceback())
	return build_envelope("UNEXPECTED")


def resource_action(func):
	"""Guarantee a whitelisted action endpoint fails as a clean envelope, never a bare
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
