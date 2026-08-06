from __future__ import annotations

import functools
import inspect
from collections.abc import Callable

import frappe
from frappe import _

from central.iam import can


def require_service_capability(capability: str) -> Callable:
	"""Gate a service endpoint on a team capability. Team access to services is
	capability-scoped (central.iam), not Frappe roles — so team users hold no DocType
	permission and every endpoint passes through this instead. Resolves the team from
	the call: a `team` arg, else the `managed_service`, else a Service API Key `name`."""

	def decorator(func: Callable) -> Callable:
		@functools.wraps(func)
		def wrapper(*args, **kwargs):
			assert_capability(_resolve_team(func, args, kwargs), capability)
			return func(*args, **kwargs)

		return wrapper

	return decorator


def _resolve_team(func: Callable, args: tuple, kwargs: dict) -> str:
	bound = inspect.signature(func).bind_partial(*args, **kwargs).arguments
	if bound.get("team"):
		return bound["team"]

	managed_service = bound.get("managed_service")
	if not managed_service and bound.get("name"):
		managed_service = frappe.db.get_value("Service API Key", bound["name"], "managed_service")

	team = frappe.db.get_value("Managed Service", managed_service, "team") if managed_service else None
	if not team:
		frappe.throw(_("Unknown managed service."), frappe.DoesNotExistError)

	return team


def assert_site_owner(site: str, team: str) -> None:
	"""A site must belong to the team consuming the service.

	Currently unreferenced — kept as the ready-made ownership guard for per-site
	service actions (e.g. site-scoped credential ops) when such an endpoint lands."""
	owner = frappe.db.get_value("Site", site, "team")
	if not owner:
		frappe.throw(_("Unknown site {0}.").format(site))

	if owner != team:
		frappe.throw(_("Site {0} does not belong to this team.").format(site), frappe.PermissionError)


def assert_capability(team: str, capability: str) -> None:
	"""Gate a team-scoped service action on an IAM capability (service:view reads,
	service:manage mutations). Operators bypass via System Manager."""
	if not can(frappe.session.user, team, capability):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def assert_operator() -> None:
	"""Platform-operator gate for backend registration (System Manager only)."""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted."), frappe.PermissionError)
