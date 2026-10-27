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
ACCEPT_DATUM_TOKEN_PATH = "/api/method/cargo.telemetry.api.auth.accept_datum_token"
ONE_CLICK_API_PATH = "/api/method/cargo.image_builder.api.one_click_image"
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

	def accept_datum_token(self, token: str) -> None:
		"""Hand Cargo the token it ships its own telemetry to the region's Datum with."""
		headers = {
			TOKEN_HEADER: mint_cargo_token(self.instance.get_atlas_region_id()),
			"Accept": "application/json",
		}

		try:
			response = requests.post(
				f"{self._base_url()}{ACCEPT_DATUM_TOKEN_PATH}",
				headers=headers,
				json={"token": token},
				timeout=(5, 20),
			)
		except requests.RequestException:
			frappe.throw(_("Cargo could not be reached to accept its Datum token."), CargoConnectionError)

		if response.status_code != 200:
			frappe.throw(
				_("Cargo rejected its Datum token (HTTP {0}).").format(response.status_code),
				CargoConnectionError,
			)

	def get_templates(self) -> list[dict]:
		"""The one-click images this region's Cargo has built, newest per application."""
		return self._get_one_click("get_supported_one_click_images")

	def get_template_requirements(self, application: str) -> dict:
		"""The inputs, smallest machine and ports one template needs."""
		return self._get_one_click("get_one_click_image_requirements", application=application)

	def get_template_user_data(self, application: str, inputs: dict[str, str]) -> str:
		"""Cloud-init user data carrying the answers to one template's inputs. Cargo checks each
		answer, so a rejected one comes back as its message."""
		try:
			response = requests.post(
				f"{self._base_url()}{ONE_CLICK_API_PATH}.get_one_click_image_user_data",
				headers=self._one_click_headers(),
				json={"application": application, "inputs": inputs},
				timeout=(5, 20),
				allow_redirects=False,
			)
		except requests.RequestException:
			frappe.throw(_("Cargo could not be reached for the template's settings."), CargoConnectionError)

		if response.status_code == 417:
			frappe.throw(_("Check the template settings: {0}").format(_cargo_message(response)))
		if response.status_code != 200:
			frappe.throw(
				_("Cargo could not prepare the template (HTTP {0}).").format(response.status_code),
				CargoConnectionError,
			)

		return response.json()["message"]

	def _one_click_headers(self) -> dict[str, str]:
		return {
			TOKEN_HEADER: mint_cargo_token(self.instance.get_atlas_region_id()),
			"Accept": "application/json",
		}

	def _get_one_click(self, method: str, **params) -> list | dict:
		try:
			response = requests.get(
				f"{self._base_url()}{ONE_CLICK_API_PATH}.{method}",
				headers=self._one_click_headers(),
				params=params,
				timeout=(5, 20),
				allow_redirects=False,
			)
		except requests.RequestException:
			frappe.throw(_("Cargo could not be reached for templates."), CargoConnectionError)

		if response.status_code != 200:
			frappe.throw(
				_("Cargo could not list templates (HTTP {0}).").format(response.status_code),
				CargoConnectionError,
			)

		return response.json()["message"]

	def _base_url(self) -> str:
		return self.instance.get_cargo_url()


def _cargo_message(response: requests.Response) -> str:
	"""The message Cargo threw for a request it found invalid."""
	try:
		messages = frappe.parse_json(response.json()["_server_messages"])
		message = frappe.parse_json(messages[-1])["message"]
	except (ValueError, KeyError, IndexError, TypeError):
		return _("Cargo gave no reason.")

	return frappe.utils.strip_html(message) if isinstance(message, str) else _("Cargo gave no reason.")
