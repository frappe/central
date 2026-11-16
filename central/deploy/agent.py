from __future__ import annotations

from typing import TYPE_CHECKING

import frappe
import requests
from frappe import _

from central.sso import mint_deploy_agent_token

if TYPE_CHECKING:
	from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine

AGENT_PORT = 7070
AGENT_TIMEOUT = (5, 30)


class DeployAgentError(frappe.ValidationError):
	"""The deploy agent refused a call or could not be reached."""


class DeployAgent:
	"""Calls to the deploy agent on an app's VM, over the VM's WireGuard mesh address."""

	def __init__(self, server: VirtualMachine) -> None:
		if not server.ipv6_address:
			frappe.throw(_("The server has no mesh address yet."), DeployAgentError)
		self.server = server
		self.base_url = f"http://[{server.ipv6_address}]:{AGENT_PORT}"

	def get_health(self) -> dict:
		return self._request("GET", "health")

	def start_build(self, payload: dict) -> dict:
		"""Start a build. The agent answers at once with the build's ID; the build runs on."""
		return self._request("POST", "builds", payload)

	def get_build(self, build_id: str) -> dict:
		return self._request("GET", f"builds/{build_id}")

	def cancel_build(self, build_id: str) -> dict:
		return self._request("POST", f"builds/{build_id}/cancel")

	def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
		headers = {"Authorization": f"Bearer {mint_deploy_agent_token(self.server.name)}"}
		try:
			response = requests.request(
				method, f"{self.base_url}/{path}", headers=headers, json=payload, timeout=AGENT_TIMEOUT
			)
		except requests.RequestException as error:
			frappe.throw(_("The deploy agent could not be reached: {0}").format(str(error)), DeployAgentError)

		if not response.ok:
			frappe.throw(
				_("The deploy agent returned HTTP {0}: {1}").format(
					response.status_code, response.text[:200]
				),
				DeployAgentError,
			)
		return response.json()
