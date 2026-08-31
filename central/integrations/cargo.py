from __future__ import annotations

import functools
import typing
from collections.abc import Callable

import frappe
from frappe import _

from central.sso import verify_cargo_token

if typing.TYPE_CHECKING:
	from frappe.frappeclient import FrappeClient

	from central.central.doctype.cargo_instance.cargo_instance import CargoInstance

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


def cargo_client(instance) -> "FrappeClient":
	"""A client bound to one Cargo host, authenticated with its own API credentials."""
	from frappe.frappeclient import FrappeClient

	client = FrappeClient(instance.base_url.rstrip("/"))
	client.session.headers.update(
		{"Authorization": f"token {instance.api_key}:{instance.get_password('api_secret')}"}
	)

	return client


def cargo_status(instance: CargoInstance) -> dict:
	"""What the host reports about itself."""
	return cargo_client(instance).get_api("cargo.api.central.status")


def register_cargo(instance: CargoInstance) -> dict:
	"""Mint this host's token and push it, with the upstream URLs, into its settings.

	Re-registering mints a fresh token, so the previous one stops working -- which is how
	a compromised host is cut off."""
	from central.sso import central_url, mint_cargo_tokens

	atlas = frappe.db.get_value(
		"Atlas Instance",
		{"region": instance.region},
		["base_url"],
		as_dict=True,
	)
	if not atlas:
		frappe.throw(_(f"No Atlas is registered for {instance.region}."))

	tokens = mint_cargo_tokens()
	# Cargo requires central and Atlas URLs along with their access tokens (issued by central) to be able to reach them.
	cargo_client(instance).post_api(
		"cargo.api.central.configure",
		{"central_url": central_url(), "atlas_url": atlas.base_url, **tokens},
	)

	status = cargo_status(instance)
	if not status.get("configured"):
		frappe.throw(_(f"{instance.base_url} accepted its settings but reports itself unconfigured."))

	instance.update(
		{
			**tokens,
			"status": "Registered",
			"reachable": 1,
			"last_synced_at": frappe.utils.now_datetime(),
		}
	)
	instance.save(ignore_permissions=True)

	return {"registered": True, "region": instance.region, **status}
