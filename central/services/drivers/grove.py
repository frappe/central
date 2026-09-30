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
		# A site's key is just a key whose Grove identity is derived from the site.
		return self.provision_key(backend, site, self._service_email(site), options)

	def provision_user(self, backend, name: str, email: str) -> None:
		# Register a Grove user. Grove upserts by email, so a repeat is safe. Free for
		# now: Grove records the usage and its cost, and charges and gates nothing.
		self._call(backend, "grove.api.provision_user", {"name": name, "email": email, "free": True})

	def provision_key(self, backend, name: str, email: str, options: dict) -> dict:
		# Mint a key for the Grove user `email`, titled `name`. Grove decides the models
		# and the limits, so `options` is not sent.
		result = self._call(backend, "grove.api.provision_key", {"email": email, "title": name})

		return {
			"gateway_url": result["gateway_url"],
			"api_key": result["api_key"],
			"provider_ref": email,
		}

	def revoke_site(self, backend, api_key: str) -> None:
		# Grove revokes by the presented key itself (it stores only the hash).
		self._call(backend, "grove.api.revoke_key", {"api_key": api_key})

	def enroll(self, base_url: str, bootstrap_secret: str) -> dict:
		# Bootstrap: no stored creds yet — the shared secret is the only auth. Grove
		# mints Central's own scoped user + key and returns them.
		url = f"{base_url.rstrip('/')}/api/method/grove.api.create_control_client"
		body = {"email": f"central@{frappe.local.site}", "token": bootstrap_secret}
		response = requests.post(url, json=body, timeout=_TIMEOUT)

		if response.status_code >= 400:
			frappe.throw(
				_("Grove enrollment failed ({0}): {1}").format(response.status_code, response.text[:200])
			)

		return response.json().get("message", {})

	def list_models(self, backend, email: str | None = None) -> list[dict]:
		# Every published model, or with `email` only what that Grove user may call.
		return self._call(backend, "grove.api.available_models", {"email": email}) or []

	def fetch_usage(
		self, backend, emails: list[str], month: str | None = None, period: str | None = None
	) -> dict:
		body = {"users": emails, "month": month, "period": period}
		return self._call(backend, "grove.api.usage", body)

	def add_credit(self, backend, email: str, amount: float, reference: str | None = None) -> dict:
		# USD, onto the Grove user's ledger. Grove books one `reference` once, so a call
		# with no answer can be sent again under it.
		body = {"email": email, "amount": amount, "reference": reference}
		return self._call(backend, "grove.api.add_credit", body)

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
			frappe.throw(
				_("Grove request failed ({0}): {1}").format(response.status_code, response.text[:200])
			)

		return response.json().get("message", {})
