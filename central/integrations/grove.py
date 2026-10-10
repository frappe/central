from __future__ import annotations

import frappe
import requests
from frappe import _

from central.iam import user_has_operator_bypass

# Connect, read: a dashboard call must not hang on a Grove that is down.
TIMEOUT = (30, 90)


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

	def rotate_control_key(self) -> dict:
		"""A new secret for Central's own control user; the old one stops at once."""
		return self.call("grove.api.create_control_client_key")

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

	def set_key_balance_access(self, user: str, key: str, can_read_balance: bool) -> dict:
		"""Let one of the user's keys read their credit at the gateway's /v1/credits, or stop it."""
		return self.call(
			"grove.api.set_key_balance_access", user=user, key=key, can_read_balance=can_read_balance
		)

	def list_models(self, user: str | None = None) -> list[dict]:
		"""Every published model, or with `user` only what that Grove user may call."""
		return self.call("grove.api.available_models", user=user) or []

	def get_balance(self, user: str) -> dict:
		"""`balance` and `spent` in USD as of Grove's last pull, and `is_free_user`."""
		return self.call("grove.api.balance", user=user)

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
		detail = f"{response.status_code}: {response.text[:2000]}"
		frappe.log_error(title="Grove request failed", message=detail)
		if user_has_operator_bypass():
			frappe.throw(_("Grove request failed ({0})").format(detail[:200]))
		frappe.throw(_("The AI service could not complete the request. Try again later."))

	return response.json().get("message", {})
