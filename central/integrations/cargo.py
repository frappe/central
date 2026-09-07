from __future__ import annotations

import functools
import inspect
from collections.abc import Callable

import frappe
from frappe import _

from central.sso import verify_cargo_access_token

TOKEN_HEADER = "X-Cargo-Token"
BOOTSTRAP_HEADER = "X-Cargo-Bootstrapping-Token"


def verify_cargo_request(func: Callable) -> Callable:
	"""Authenticates Cargo's signed token before the handler runs, stashing the verified
	claims on frappe.local, and refuses a host asking about a region that is not its own.
	functools.wraps is required — Frappe maps request args off the wrapped signature."""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		frappe.local.cargo_request = _authenticate_cargo_request()
		_assert_own_region(func, args, kwargs)
		return func(*args, **kwargs)

	return wrapper


def verify_cargo_bootstrapping_request(func: Callable) -> Callable:
	"""Authenticates a host enrolling for the first time, stashing the Cargo Instance it
	named on frappe.local. functools.wraps is required -- Frappe maps request args off the
	wrapped signature."""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		frappe.local.cargo_instance = _authenticate_bootstrapping_request()
		return func(*args, **kwargs)

	return wrapper


def _authenticate_bootstrapping_request() -> str:
	"""The Cargo Instance the presented token was minted for.

	Spent tokens are refused: a host enrols once per token, so a leaked one cannot be
	replayed to collect a second set of credentials. The row is locked for the rest of the
	request, which is what makes "once" hold when the replay arrives concurrently."""
	from central.sso import verify_cargo_bootstrapping_token

	token = (frappe.get_request_header(BOOTSTRAP_HEADER) or "").strip()
	if not token:
		frappe.throw(_("A Cargo bootstrapping token is required."), frappe.AuthenticationError)

	instance = verify_cargo_bootstrapping_token(token)
	status = _lock_awaiting_enrolment(instance)

	stored = frappe.utils.password.get_decrypted_password(
		"Cargo Instance", instance, "bootstrapping_token", raise_exception=False
	)
	# Draft with a different token means the operator re-issued one; this one is stale.
	if status != "Draft" or stored != token:
		frappe.throw(_("This bootstrapping token has already been used."), frappe.AuthenticationError)

	return instance


def _lock_awaiting_enrolment(instance: str) -> str:
	"""Just take a lock"""
	status = frappe.db.get_value("Cargo Instance", instance, "status", for_update=True)
	if not status:
		frappe.throw(_("This token names no known Cargo host."), frappe.AuthenticationError)

	return status


def _authenticate_cargo_request() -> frappe._dict:
	"""Central signed the token, so it verifies its own signature -- no shared secret.

	The token rides its own header: Frappe rejects any two-part `Authorization` header
	that does not resolve to a user, before a guest endpoint is ever reached.

	The claims come back carrying the region of the Cargo Instance the token names, which
	is the region the caller is allowed to act on."""
	token = (frappe.get_request_header(TOKEN_HEADER) or "").strip()
	if not token:
		frappe.throw(_("A Cargo token is required."), frappe.AuthenticationError)

	claims = frappe._dict(verify_cargo_access_token(token))
	instance = frappe.db.get_value("Cargo Instance", claims.instance, ["region", "status"], as_dict=True)
	if not instance:
		frappe.throw(_("This token names no known Cargo host."), frappe.AuthenticationError)
	if instance.status == "Disabled":
		frappe.throw(_("This Cargo host is disabled."), frappe.AuthenticationError)

	claims.region = instance.region

	return claims


def _assert_own_region(func: Callable, args: tuple, kwargs: dict) -> None:
	"""A Cargo host acts on one region: the one its token was minted for.

	The region still arrives as an argument so a host pointed at the wrong region fails
	loudly instead of silently operating on another cluster's secrets and endpoints."""
	if "region" not in inspect.signature(func).parameters:
		return

	requested = inspect.signature(func).bind_partial(*args, **kwargs).arguments.get("region")
	if requested != frappe.local.cargo_request.region:
		frappe.throw(
			_("This Cargo token is not for region {0}.").format(requested or "(none)"),
			frappe.PermissionError,
		)
