from __future__ import annotations

import frappe
import requests
from frappe import _

TIMEOUT = 30


class GroveClient:
	"""Calls Grove's control API (`grove.api`) as Central. A team is one Grove user, named by the
	team id. Grove owns the keys, models and limits; Central never proxies inference."""

	def __init__(self, base_url: str, api_key: str, api_secret: str):
		self.base_url = base_url
		self.headers = {"Authorization": f"token {api_key}:{api_secret}"}

	@classmethod
	def from_settings(cls) -> GroveClient:
		settings = frappe.get_cached_doc("AI Settings")
		if not settings.base_url or not settings.control_api_key:
			frappe.throw(_("AI is not set up: enroll Central at Grove in AI Settings."))
		return cls(settings.base_url, settings.control_api_key, settings.get_password("control_api_secret"))

	@staticmethod
	def enroll(base_url: str, bootstrap_secret: str) -> dict:
		"""Mint Central's own control user and key at Grove. The shared secret is the only auth."""
		body = {"email": f"central@{frappe.local.site}", "token": bootstrap_secret}
		response = requests.post(
			f"{base_url}/api/method/grove.api.create_control_client", json=body, timeout=TIMEOUT
		)
		return read(response)

	def provision_user(self, user: str, email: str, free: bool = False) -> dict:
		"""Register `user`, or send its new `email` (an alert address, not a login). Grove upserts
		by `user` and pins it to its default geography. With `free`, Grove charges and gates
		nothing; without it, Grove keeps the setting it has."""
		return self.call("grove.api.provision_user", user=user, email=email, free=free)

	def provision_key(self, user: str, title: str) -> dict:
		"""Mint a key: its `name`, `gateway_url` and `api_key`. The secret is never sent again."""
		return self.call("grove.api.provision_key", user=user, title=title)

	def list_keys(self, user: str) -> list[dict]:
		return self.call("grove.api.keys", user=user) or []

	def revoke_key(self, user: str, key: str) -> None:
		self.call("grove.api.revoke_key", user=user, key=key)

	def list_models(self, user: str | None = None) -> list[dict]:
		"""Every published model, or with `user` only what that Grove user may call."""
		return self.call("grove.api.available_models", user=user) or []

	def get_limits(self, user: str) -> list[dict]:
		"""Rows of `metric`, `window` and `value`."""
		return self.call("grove.api.limits", user=user) or []

	def get_usage(
		self,
		users: list[str],
		month: str | None = None,
		period: str | None = None,
		key_hash: str | None = None,
	) -> dict:
		return self.call("grove.api.usage", users=users, month=month, period=period, key_hash=key_hash)

	def add_credit(self, user: str, amount: float, reference: str | None = None) -> dict:
		"""USD onto the Grove user's ledger. Grove books one `reference` once, so a call with no
		answer can be sent again under it."""
		return self.call("grove.api.add_credit", user=user, amount=amount, reference=reference)

	def call(self, method: str, **body) -> dict | list:
		response = requests.post(
			f"{self.base_url}/api/method/{method}", json=body, headers=self.headers, timeout=TIMEOUT
		)
		return read(response)


def read(response: requests.Response) -> dict | list:
	if response.status_code >= 400:
		frappe.throw(_("Grove request failed ({0}): {1}").format(response.status_code, response.text[:200]))
	return response.json().get("message", {})
