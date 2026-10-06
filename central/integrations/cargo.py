from __future__ import annotations

from typing import TYPE_CHECKING

import frappe
import requests
from frappe import _

from central.errors import CargoConnectionError
from central.sso import central_url, mint_cargo_token

if TYPE_CHECKING:
	from central.infrastructure.doctype.region.region import Region

PING_PATH = "/api/method/ping"
CONFIGURE_WEBHOOKS_PATH = "/api/method/cargo.api.webhooks.configure"
TOKEN_HEADER = "X-Cargo-Access-Token"


class CargoClient:
	"""Central's outbound calls to one region's Cargo host: a readiness check and the
	one-time handoff of the secret Cargo signs its own reports with. Cargo has no
	polled connection test of its own — see `cargo_connection.py` — so this client only
	ever runs as part of enrollment, never on demand from an operator."""

	def __init__(self, instance: Region):
		self.instance = instance

	def is_answering(self) -> bool:
		"""Whether this region's Cargo answers Frappe's own liveness check yet."""
		try:
			response = requests.get(f"{self._base_url()}{PING_PATH}", timeout=(5, 10))
		except requests.RequestException:
			return False

		try:
			body = response.json()
		except requests.exceptions.JSONDecodeError:
			return False

		return response.status_code == 200 and body.get("message") == "pong"

	def configure_webhooks(self, webhook_secret: str) -> None:
		"""Hand Cargo the secret it will sign its own service reports with, and where to
		send them. Cargo authenticates the call itself, against Central's JWKS."""
		region_id = self.instance.get_atlas_region_id()
		payload = {
			"request_url": f"{central_url()}/api/method/central.api.state_delivery.receive",
			"webhook_secret": webhook_secret,
			"enabled": True,
		}
		headers = {TOKEN_HEADER: mint_cargo_token(region_id), "Accept": "application/json"}

		try:
			response = requests.post(
				f"{self._base_url()}{CONFIGURE_WEBHOOKS_PATH}", headers=headers, json=payload, timeout=(5, 20)
			)
		except requests.RequestException:
			frappe.throw(_("Cargo could not be reached to configure its webhooks."), CargoConnectionError)

		if response.status_code not in (200, 201):
			frappe.throw(
				_("Cargo rejected webhook configuration (HTTP {0}).").format(response.status_code),
				CargoConnectionError,
			)

	def _base_url(self) -> str:
		return self.instance.get_cargo_url()
