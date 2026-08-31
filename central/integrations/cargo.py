from __future__ import annotations

import functools
from collections.abc import Callable

import frappe
from frappe import _

from central.sso import verify_cargo_access_token

TOKEN_HEADER = "X-Cargo-Token"
BOOTSTRAP_HEADER = "X-Cargo-Bootstrapping-Token"


def verify_cargo_request(func: Callable) -> Callable:
	"""Authenticates Cargo's signed token before the handler runs, stashing the verified
	claims on frappe.local. functools.wraps is required — Frappe maps request args off the
	wrapped signature."""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		frappe.local.cargo_request = _authenticate_cargo_request()
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
	replayed to collect a second set of credentials."""
	from central.sso import verify_cargo_bootstrapping_token

	token = (frappe.get_request_header(BOOTSTRAP_HEADER) or "").strip()
	if not token:
		frappe.throw(_("A Cargo bootstrapping token is required."), frappe.AuthenticationError)

	instance = verify_cargo_bootstrapping_token(token)
	if not frappe.db.exists("Cargo Instance", instance):
		frappe.throw(_("This token names no known Cargo host."), frappe.AuthenticationError)

	stored = frappe.utils.password.get_decrypted_password(
		"Cargo Instance", instance, "bootstrapping_token", raise_exception=False
	)
	if stored != token:
		frappe.throw(_("This bootstrapping token has already been used."), frappe.AuthenticationError)

	return instance


def _authenticate_cargo_request() -> frappe._dict:
	"""Central signed the token, so it verifies its own signature -- no shared secret.

	The token rides its own header: Frappe rejects any two-part `Authorization` header
	that does not resolve to a user, before a guest endpoint is ever reached."""
	token = (frappe.get_request_header(TOKEN_HEADER) or "").strip()
	if not token:
		frappe.throw(_("A Cargo token is required."), frappe.AuthenticationError)

	return frappe._dict(verify_cargo_access_token(token))
