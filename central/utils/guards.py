from __future__ import annotations

import functools
import inspect
from collections.abc import Callable

import frappe

from central.iam import can, is_active_team_member, user_has_operator_bypass

# Authorization decorators for the whitelisted Team endpoints — the guard runs
# before the handler body. Ordered under @frappe.whitelist (which stays outermost);
# functools.wraps keeps the original signature so Frappe still maps request args.


def _call_arg(func: Callable, args: tuple, kwargs: dict, name: str):
	"""Read a named argument from the call, whether passed positionally or by keyword."""
	return inspect.signature(func).bind_partial(*args, **kwargs).arguments.get(name)


def require_team_member(func: Callable) -> Callable:
	"""Gate a team-scoped read on active membership of the `team` argument; operators bypass."""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		team = _call_arg(func, args, kwargs, "team")
		if not user_has_operator_bypass() and not is_active_team_member(frappe.session.user, team):
			frappe.throw("You are not a member of this team.", frappe.PermissionError)
		return func(*args, **kwargs)

	return wrapper


def require_capability(capability: str, message: str) -> Callable:
	"""Gate an endpoint on `capability` for the `team` argument; operators bypass."""

	def decorator(func: Callable) -> Callable:
		@functools.wraps(func)
		def wrapper(*args, **kwargs):
			team = _call_arg(func, args, kwargs, "team")
			# can() denies a suspended team even to operators, so keep the explicit operator fallback.
			if not can(frappe.session.user, team, capability) and not user_has_operator_bypass():
				frappe.throw(message, frappe.PermissionError)
			return func(*args, **kwargs)

		return wrapper

	return decorator


def require_self_or_operator(func: Callable) -> Callable:
	"""Gate an observe endpoint to the subject user themselves or a System Manager."""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		# `user` defaults to the caller — same resolution the handlers use.
		target = _call_arg(func, args, kwargs, "user") or frappe.session.user
		if frappe.session.user != target and "System Manager" not in frappe.get_roles():
			frappe.throw("Only System Manager can inspect another user's permissions", frappe.PermissionError)
		return func(*args, **kwargs)

	return wrapper
