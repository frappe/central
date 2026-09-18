# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Central's integration with the connect site — one site, unlike the per-region
Atlas Instances `atlas.py` talks to, so `Connect Settings` is a Single instead of a
roster doctype. Outbound only: `ConnectClient` calls connect over Frappe's own
`FrappeClient` (token auth, mirroring `AtlasClient._admin_client`), reading
`api_key`/`api_secret` off `Connect Settings`. Nothing calls central from connect yet
(see the "site-to-site auth candidate" note in the partner-persona-plan memory for the
reverse direction) — this is deliberately fetch-only for now.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.frappeclient import FrappeClient, FrappeException


class ConnectError(frappe.ValidationError):
	"""Connect is unreachable, disabled, misconfigured, or refused the request."""


def _settings():
	settings = frappe.get_single("Connect Settings")
	if not settings.enabled:
		frappe.throw(_("The connect integration is not enabled (Connect Settings)."), ConnectError)
	if not (settings.base_url and settings.api_key):
		frappe.throw(_("Connect Settings is missing a base URL or API key."), ConnectError)
	return settings


class ConnectClient:
	"""A FrappeClient bound to the connect site, authenticated with the admin
	api_key/api_secret on `Connect Settings` — the central<->connect counterpart to
	`AtlasClient` in `atlas.py`, minus the per-region roster (there's only one connect)
	and minus the tunnel/lifecycle machinery (this is a plain read integration)."""

	def __init__(self, settings=None):
		self.settings = settings or _settings()

	def client(self) -> FrappeClient:
		return FrappeClient(
			self.settings.base_url,
			api_key=self.settings.api_key,
			api_secret=self.settings.get_password("api_secret"),
		)

	def _get_doc(self, doctype: str, name: str, *, action: str) -> dict:
		"""Fetch one document from connect, translating a remote/network failure into
		`ConnectError` rather than leaking connect's raw traceback to the caller."""
		try:
			doc = self.client().get_doc(doctype, name)
		except FrappeException as exception:
			frappe.log_error(title=f"Connect: {action} failed", message=str(exception))
			frappe.throw(_("Could not reach connect to {0}.").format(action), ConnectError)
		if not doc:
			frappe.throw(_("{0} {1} was not found on connect.").format(doctype, name), ConnectError)
		return doc

	def get_partner(self, name: str) -> dict:
		"""Fetch one `Partner` (marketplace identity) record from connect by name —
		the `Partner Profile.connect_partner` reference string."""
		return self._get_doc("Partner", name, action=f"fetch partner {name}")

	def get_customer(self, name: str) -> dict:
		"""Fetch one `Customer` record from connect by name."""
		return self._get_doc("Customer", name, action=f"fetch customer {name}")
