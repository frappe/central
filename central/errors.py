from __future__ import annotations

import functools

import frappe
from frappe import _
from frappe.utils.translations import N_

# The message key the envelope rides on inside each _server_messages entry.
ENVELOPE_KEY = "action_error"


class ResourceActionError(frappe.ValidationError):
	"""A server-flow failure already shaped into a user-facing envelope."""


class AtlasConnectionError(frappe.ValidationError):
	"""A regional read or authentication/configuration check failed."""


class AtlasRejected(AtlasConnectionError):
	"""Atlas explicitly rejected a mutation before accepting it. `code` is Atlas's own
	error code, when the reply names one."""

	def __init__(self, message: str | None = None, code: str | None = None):
		super().__init__(message)
		self.code = code


# Atlas codes for "no host has room for this shape".
ATLAS_CAPACITY_CODES = frozenset({"out_of_capacity", "affinity_unsatisfied", "insufficient_capacity"})


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
		"title": N_("You don't have access"),
		"message": N_("Your role on this team isn't allowed to {action} servers."),
		"remediation": N_(
			"Ask a team admin to grant you server access, or switch to a team where you have it."
		),
		"retriable": False,
	},
	"INPUT_REQUIRED": {
		"title": N_("Missing information"),
		"message": N_("{field} is required to continue."),
		"remediation": "",
		"retriable": False,
	},
	"SERVER_NOT_FOUND": {
		"title": N_("Server not found"),
		"message": N_("We couldn't find the server '{resource_id}' on this team."),
		"remediation": N_(
			"It may have been terminated, or it belongs to another team. Refresh your server list and try again."
		),
		"retriable": False,
	},
	"SERVER_BUSY_RESIZING": {
		"title": N_("Server is resizing"),
		"message": N_(
			"This server is resizing right now. You can {action} it as soon as the resize finishes."
		),
		"remediation": "",
		"retriable": True,
	},
	"REGION_UNAVAILABLE": {
		"title": N_("This region is temporarily unavailable"),
		"message": N_("We couldn't reach the selected region."),
		"remediation": N_("Try again in a few minutes. If the problem continues, contact support."),
		"retriable": True,
	},
	"ATLAS_REJECTED": {
		"title": N_("This request couldn't be completed"),
		"message": N_("The selected region couldn't complete this request."),
		"remediation": N_("Review your selections and try again. If the problem continues, contact support."),
		"retriable": False,
	},
	"REGION_AT_CAPACITY": {
		"title": N_("No room for this size"),
		"message": N_("The selected region has no room for this server size right now."),
		"remediation": N_("Choose a smaller size, or try again later."),
		"retriable": True,
	},
	"RESOURCE_GONE": {
		"title": N_("This server is no longer available"),
		"message": N_("The server may already have been removed."),
		"remediation": N_("Refresh your server list to see the current state."),
		"retriable": False,
	},
	"ACTION_FAILED": {
		"title": N_("The {action} didn't complete"),
		"message": N_(
			"Your server reported a failure while trying to {action}, and it's now in a failed state."
		),
		"remediation": N_(
			"Review the existing server and contact support before submitting another operation."
		),
		"retriable": False,
	},
	"ACTION_TIMED_OUT": {
		"title": N_("The {action} is taking too long"),
		"message": N_("We haven't heard back that the {action} finished. It may still complete on its own."),
		"remediation": N_(
			"Refresh your server list in a few minutes. If it still looks stuck, contact support."
		),
		"retriable": False,
	},
	"CREATE_NOT_ACCEPTED": {
		"title": N_("The server wasn't created"),
		"message": N_("The selected region did not accept the request. No server was created."),
		"remediation": N_("Try again, or select another region if the problem continues."),
		"retriable": True,
	},
	"SNAPSHOT_FAILED": {
		"title": N_("The final snapshot didn't complete"),
		"message": N_("The snapshot failed, so the server was not removed. The server is stopped."),
		"remediation": N_("Start the server again, or terminate it without a snapshot."),
		"retriable": True,
	},
	"OUTCOME_UNKNOWN": {
		"title": N_("We're still confirming this request"),
		"message": N_("We couldn't confirm whether the selected region accepted it."),
		"remediation": N_("We'll keep checking. Don't submit the request again."),
		"retriable": False,
	},
	"REFRESH_FAILED": {
		"title": N_("Progress isn't available yet"),
		"message": N_("Your request was accepted, but we couldn't load its latest status."),
		"remediation": N_("We'll check again automatically. Don't submit another request."),
		"retriable": False,
	},
	"FINALIZATION_FAILED": {
		"title": N_("Setup needs support"),
		"message": N_("The selected region accepted the request, but setup did not finish."),
		"remediation": N_("Don't submit another request. Contact support with this action ID."),
		"retriable": False,
	},
	"VALIDATION_ERROR": {
		"title": N_("Check the request details"),
		"message": N_("The request could not be completed with these details."),
		"remediation": N_(
			"Review the information you entered. Contact support if you cannot resolve the problem."
		),
		"retriable": False,
	},
	"PAYMENT_METHOD_REQUIRED": {
		"title": N_("Add a payment method to create servers"),
		"message": N_("Your credit does not cover this server, and your team has no payment method."),
		"remediation": N_(
			"Open Billing to add your billing details and a payment method. Ask a team admin if you cannot manage billing."
		),
		"retriable": False,
	},
	"PAYMENT_OVERDUE": {
		"title": N_("Pay what your team owes to continue"),
		"message": N_(
			"Your team has an unpaid invoice that is overdue, or its account is past due or suspended."
		),
		"remediation": N_(
			"Open Billing and pay the unpaid invoice. Ask a team admin if you cannot manage billing."
		),
		"retriable": False,
	},
	"TRIAL_IN_PROGRESS": {
		"title": N_("You already have a free trial"),
		"message": N_("Your {product} trial at {address} is still open."),
		"remediation": N_("Use that site, or delete it to start a new trial."),
		"retriable": False,
	},
	"TRUST_TIER_LIMIT": {
		"title": N_("Your trust tier limit is reached"),
		"message": N_("Your trust tier allows {limit} servers, and your team already has {count}."),
		"remediation": N_(
			"Terminate a server you no longer need, or contact support to review your trust tier."
		),
		"retriable": False,
	},
	"MAILBOX_POOL_EMPTY": {
		"title": N_("The server wasn't created"),
		"message": N_("This region has no mailbox ready for a new server. No server was created."),
		"remediation": N_("Try again in a few minutes."),
		"retriable": True,
	},
	"UNEXPECTED": {
		"title": N_("We couldn't complete that"),
		"message": N_("Something went wrong while we were processing your request."),
		"remediation": N_("Check its status before trying again. If the result is unclear, contact support."),
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
		return build_envelope("REGION_AT_CAPACITY" if exc.code in ATLAS_CAPACITY_CODES else "ATLAS_REJECTED")
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
	"""Return customer-safe errors from a resource endpoint: a catalog envelope with a stable
	`code` the console switches on, never a bare exception or a traceback."""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		try:
			return func(*args, **kwargs)
		except Exception as exc:
			if getattr(exc, "envelope", None):
				raise

			envelope = to_error_response(exc)
			# The user sees only generic copy, so keep the traceback for the operator.
			if envelope["code"] == "UNEXPECTED":
				# No frame locals: a remote call's frames hold its bearer token.
				frappe.log_error(title="Unexpected server-action error", message=frappe.get_traceback())
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
