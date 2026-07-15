from __future__ import annotations

import frappe
import requests
from frappe import _

_TIMEOUT = 30


class GroveDriver:
	"""Talks to a Grove LLM-hosting deployment. Grove mints long-lived per-consumer
	API keys; Central stores and delivers them and never proxies inference."""

	key = "grove"

	def provision_site(self, backend, site: str, options: dict) -> dict:
		result = self._call(
			backend,
			"grove.api.provision_key",
			{
				"name": site,
				"email": self._service_email(site),
				"token_limit": options.get("token_limit"),
				"allowed_models": options.get("allowed_models"),
			},
		)

		return {
			"gateway_url": result["gateway_url"],
			"api_key": result["api_key"],
			"provider_ref": self._service_email(site),
		}

	def revoke_site(self, backend, api_key: str) -> None:
		# Grove revokes by the presented key itself (it stores only the hash).
		self._call(backend, "grove.api.revoke_key", {"api_key": api_key})

	def enroll(self, base_url: str, bootstrap_secret: str) -> dict:
		# Bootstrap: no stored creds yet — the shared secret is the only auth. Grove
		# mints Central's own scoped user + key and returns them.
		url = f"{base_url.rstrip('/')}/api/method/grove.api.enroll_control_client"
		response = requests.post(url, json={"bootstrap_token": bootstrap_secret}, timeout=_TIMEOUT)

		if response.status_code >= 400:
			frappe.throw(_("Grove enrollment failed ({0}): {1}").format(response.status_code, response.text[:200]))

		return response.json().get("message", {})

	def list_models(self, backend) -> list[dict]:
		return self._call(backend, "grove.api.available_models", {}) or []

	def fetch_usage(self, backend, emails: list[str], month: str | None = None) -> dict:
		return self._call(backend, "grove.api.usage", {"users": emails, "month": month})

	# A stable, valid synthetic address keeps Grove's provision_key idempotent per
	# site (it upserts a Grove User by email).
	def _service_email(self, site: str) -> str:
		return f"{site.replace('.', '-')}@svc.frappe.cloud"

	def _call(self, backend, method: str, body: dict) -> dict:
		secret = backend.get_password("control_api_secret")
		headers = {"Authorization": f"token {backend.control_api_key}:{secret}"}
		url = f"{backend.base_url.rstrip('/')}/api/method/{method}"

		response = requests.post(url, json=body, headers=headers, timeout=_TIMEOUT)
		if response.status_code >= 400:
			frappe.throw(_("Grove request failed ({0}): {1}").format(response.status_code, response.text[:200]))

		return response.json().get("message", {})
