from __future__ import annotations

import functools
import inspect
from collections.abc import Callable

import frappe
from frappe import _

from central.iam import (
	can,
	can_on_any_server,
	is_active_team_member,
	resolve_team,
	user_has_operator_bypass,
)

# Authorization decorators for the whitelisted Team endpoints — the guard runs
# before the handler body. Ordered under @frappe.whitelist (which stays outermost);
# functools.wraps keeps the original signature so Frappe still maps request args.


@functools.cache
def _signature(func: Callable) -> inspect.Signature:
	# A function's signature never changes, so resolve it once and cache it —
	# `inspect.signature` is the expensive part and this runs on every gated request.
	return inspect.signature(func)


def _bound_call(func: Callable, args: tuple, kwargs: dict) -> inspect.BoundArguments:
	"""Bind one call so guards can read or replace positional and keyword arguments."""
	return _signature(func).bind_partial(*args, **kwargs)


def _call_arg(func: Callable, args: tuple, kwargs: dict, name: str):
	"""Read one named argument from the call."""
	return _bound_call(func, args, kwargs).arguments.get(name)


def _resolve_team_call(func: Callable, args: tuple, kwargs: dict) -> inspect.BoundArguments:
	bound = _bound_call(func, args, kwargs)
	bound.arguments["team"] = resolve_team(frappe.session.user, bound.arguments.get("team"))
	return bound


def require_team_member(func: Callable) -> Callable:
	"""Gate a team-scoped read on active membership of the `team` argument; operators bypass."""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		bound = _resolve_team_call(func, args, kwargs)
		team = bound.arguments["team"]
		if not user_has_operator_bypass() and not is_active_team_member(frappe.session.user, team):
			frappe.throw(_("You are not a member of this team."), frappe.PermissionError)
		return func(*bound.args, **bound.kwargs)

	return wrapper


def require_capability(capability: str, message: str, server: str | None = None) -> Callable:
	"""Gate an endpoint on `capability` for the `team` argument; operators bypass.

	1. When the argument named by `server` holds a server, the user needs the capability
	   on that server.
	2. Otherwise the user needs it team-wide or on at least one server of the team. A
	   route that then reads a list relies on the permission rules to narrow it."""

	def decorator(func: Callable) -> Callable:
		@functools.wraps(func)
		def wrapper(*args, **kwargs):
			bound = _resolve_team_call(func, args, kwargs)
			team = bound.arguments["team"]
			server_name = bound.arguments.get(server) if server else None
			if server_name:
				allowed = can(frappe.session.user, team, capability, server=server_name)
			else:
				allowed = can_on_any_server(frappe.session.user, team, capability)
			if not allowed:
				frappe.throw(_(message), frappe.PermissionError)
			return func(*bound.args, **bound.kwargs)

		return wrapper

	return decorator


def require_self_or_operator(func: Callable) -> Callable:
	"""Gate an observe endpoint to the subject user themselves or a System Manager."""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		# `user` defaults to the caller — same resolution the handlers use.
		target = _call_arg(func, args, kwargs, "user") or frappe.session.user
		if frappe.session.user != target and "System Manager" not in frappe.get_roles():
			frappe.throw(
				_("Only System Manager can inspect another user's permissions"), frappe.PermissionError
			)
		return func(*args, **kwargs)

	return wrapper
