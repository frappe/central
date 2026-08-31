from __future__ import annotations

import functools
from collections.abc import Callable

import frappe
from frappe import _

from central.sso import verify_cargo_token

TOKEN_HEADER = "X-Cargo-Token"


def verify_cargo_request(func: Callable) -> Callable:
	"""Authenticates Cargo's signed token before the handler runs, stashing the verified
	claims on frappe.local. functools.wraps is required — Frappe maps request args off the
	wrapped signature."""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		frappe.local.cargo_request = _authenticate_cargo_request()
		return func(*args, **kwargs)

	return wrapper


def _authenticate_cargo_request() -> frappe._dict:
	"""Central signed the token, so it verifies its own signature -- no shared secret.

	The token rides its own header: Frappe rejects any two-part `Authorization` header
	that does not resolve to a user, before a guest endpoint is ever reached."""
	token = (frappe.get_request_header(TOKEN_HEADER) or "").strip()
	if not token:
		frappe.throw(_("A Cargo token is required."), frappe.AuthenticationError)

	return frappe._dict(verify_cargo_token(token))
