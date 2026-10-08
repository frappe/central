from __future__ import annotations

import frappe
import requests
from frappe import _

# Connect, read: a dashboard call must not hang on a Grove that is down.
TIMEOUT = (30, 90)


class GroveClient:
	"""Calls Grove's control API (`grove.api`) as Central. A team is one Central Team at Grove,
	named by the team id; each of its keys carries its own geography, models, rate limits and
	cap. Grove owns the keys; Central never proxies inference."""

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

	def provision_team(self, team: str, email: str, free: bool = False) -> dict:
		"""Register `team`, or send its new `email` (an alert address, not a login). Grove upserts
		by `team`. With `free`, Grove charges and gates nothing; without it, Grove keeps the
		setting it has. → `team` and `max_keys`, how many live keys it may hold."""
		return self.call("grove.api.provision_team", team=team, email=email, free=free)

	def provision_key(
		self, team: str, title: str, geography: str | None = None, cap: float | None = None
	) -> dict:
		"""Mint a key in `geography` (Grove's default when None) with `cap` USD to spend (required
		above zero on a prepaid team): its `name`, `geography`, `gateway_url` and `api_key`. The
		secret is never sent again."""
		return self.call("grove.api.provision_key", team=team, title=title, geography=geography, cap=cap)

	def update_key(self, team: str, key: str, cap: float | None = None) -> dict:
		"""Change what a key may spend. → the key as `list_keys` lists it."""
		return self.call("grove.api.update_key", team=team, key=key, cap=cap)

	def list_keys(self, team: str) -> list[dict]:
		return self.call("grove.api.keys", team=team) or []

	def revoke_key(self, team: str, key: str) -> None:
		self.call("grove.api.revoke_key", team=team, key=key)

	def list_models(
		self, team: str | None = None, key: str | None = None, geography: str | None = None
	) -> list[dict]:
		"""What a new key in `geography` (Grove's default when None) starts with: the published
		models of its default group. With `team` and `key`, what that one key may call."""
		return self.call("grove.api.available_models", team=team, key=key, geography=geography) or []

	def list_geographies(self) -> list[dict]:
		"""Where a key may be minted: `name`, `label`, `endpoint`, `is_default`."""
		return self.call("grove.api.geographies") or []

	def get_balance(self, team: str) -> dict:
		"""`balance`, `spent` and `unallocated` in USD as of Grove's last pull, and `is_free_user`."""
		return self.call("grove.api.balance", team=team)

	def get_usage(
		self,
		teams: list[str],
		month: str | None = None,
		period: str | None = None,
		key_hash: str | None = None,
	) -> dict:
		return self.call("grove.api.usage", teams=teams, month=month, period=period, key_hash=key_hash)

	def add_credit(self, team: str, amount: float, reference: str | None = None) -> dict:
		"""USD onto the team's ledger. Grove books one `reference` once, so a call with no
		answer can be sent again under it."""
		return self.call("grove.api.add_credit", team=team, amount=amount, reference=reference)

	def call(self, method: str, **body) -> dict | list:
		response = requests.post(
			f"{self.base_url}/api/method/{method}", json=body, headers=self.headers, timeout=TIMEOUT
		)
		return read(response)


def read(response: requests.Response) -> dict | list:
	if response.status_code >= 400:
		frappe.throw(_("Grove request failed ({0}): {1}").format(response.status_code, response.text[:200]))
	return response.json().get("message", {})
