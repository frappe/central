from __future__ import annotations

import json

import frappe
import requests
from frappe import _

from central.iam import user_has_operator_bypass

# Connect, read: a dashboard call must not hang on a Grove that is down.
TIMEOUT = (30, 90)
# What a Grove that is down or in maintenance answers; Frappe's maintenance mode is a 503.
UNAVAILABLE = (502, 503, 504)


class GroveUnavailable(frappe.ValidationError):
	"""Grove cannot be reached or is in maintenance. Its gateways keep serving keys meanwhile."""

	http_status_code = 503


class GroveClient:
	"""Calls Grove's control API (`grove.api`) as Central. A team is one Central Team at Grove,
	named by the team id, under the key count, monthly spend limit and rate limits of its tier,
	which Grove holds; each of its keys carries its own geography, models, rate limits and monthly cap. Grove owns the keys;
	Central never proxies inference. A tier change reaches Grove by the Webhook AI Settings keeps
	(`grove.api.teams.team_webhook`), not through this client."""

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
			f"{base_url}/api/method/grove.api.control.create_control_client", json=body, timeout=TIMEOUT
		)

		return read(response)

	def rotate_control_key(self) -> dict:
		"""A new secret for Central's own control user; the old one stops at once."""
		return self.call("grove.api.control.create_control_client_key")

	def provision_team(self, team: str) -> dict:
		"""Register `team` by its id; Grove keeps nothing else about who it is. Grove upserts
		by `team`; `update_team` sets everything else. → `team` and `max_keys`."""
		return self.call("grove.api.teams.provision_team", team=team)

	def update_team(
		self,
		team: str,
		suspended: bool | None = None,
		tier: str | None = None,
		observed_at: str | None = None,
		log_payloads: bool | None = None,
	) -> dict:
		"""The name of the team's `tier` at Grove ("" for none: Grove's default tier), whose key
		count, monthly spend limit and rate limits Grove holds, whether it is `suspended`, and
		whether the gateways store its prompts and outputs (`log_payloads`), each kept at Grove
		when None; `observed_at` is when Central read them, and Grove ignores a body not newer
		than its last. → the team, its `log_payloads` and the limits in force for it."""
		return self.call(
			"grove.api.teams.update_team",
			team=team,
			suspended=suspended,
			tier=tier,
			observed_at=observed_at,
			log_payloads=log_payloads,
		)

	def rename_tier(self, old: str, new: str) -> None:
		"""A trust tier label changed: Grove renames its Tier, and every team on it follows."""
		self.call("grove.api.teams.rename_tier", old=old, new=new)

	def provision_key(
		self,
		team: str,
		title: str | None,
		geography: str | None = None,
		cap: int | None = None,
		expiry: str | None = None,
		expiry_from_first_use: bool = False,
		model_group: str | None = None,
	) -> dict:
		"""Mint a key in `geography` (Grove's default when None) with `cap` whole USD to spend a
		month (0 when None: refused until it gets one), untitled when `title` is None, retiring by
		`expiry` (one of Grove's rules: Never, 1 Day, 7 Days, 14 Days, 30 Days; Never when None)
		counted from the mint or, with `expiry_from_first_use`, from its first request, in `model_group`
		(the geography's default group when None): its `name`,
		`geography`, `gateway_url` and `api_key`. The secret is never sent again."""
		body = {"team": team, "title": title, "geography": geography, "cap": cap}
		if expiry:
			body |= {"expiry": expiry, "expiry_from_first_use": expiry_from_first_use}
		if model_group:
			body["model_group"] = model_group
		return self.call("grove.api.keys.provision_key", **body)

	def update_caps(self, team: str, caps: dict[str, int]) -> list[dict]:
		"""Set several keys' monthly caps at once, {key: whole USD}; Grove saves all or none. →
		the keys as `get_figures` lists them."""
		return self.call("grove.api.keys.update_caps", team=team, caps=caps) or []

	def revoke_key(self, team: str, key: str) -> None:
		self.call("grove.api.keys.revoke_key", team=team, key=key)

	def extend_key(self, team: str, key: str, days: int) -> dict:
		"""`days` more on the key's expiry, from now or from its moment, whichever is later; a key
		without one yet is left as it is, a revoked one refused. → the key as `get_figures` lists it."""
		return self.call("grove.api.keys.extend_key", team=team, key=key, days=days)

	def list_models(
		self, team: str | None = None, key: str | None = None, geography: str | None = None
	) -> list[dict]:
		"""What a new key in `geography` (Grove's default when None) starts with: the published
		models of its default group. With `team` and `key`, what that one key may call."""
		return self.call("grove.api.catalog.available_models", team=team, key=key, geography=geography) or []

	def list_geographies(self) -> list[dict]:
		"""Where a key may be minted: `name`, `label`, `endpoint` (None while the geography has no
		gateway; a key minted there is refused), `is_default`."""
		return self.call("grove.api.catalog.geographies") or []

	def get_figures(self, team: str) -> dict:
		"""What the console shows, as one entry Grove keeps until something moves it (a record lands,
		a correction, a key or the team saved, its tier edited) and 30 minutes at most, so every
		page shows one moment. `spend` in USD: `month_spent`, `capped` (Σ live caps) and
		`committed` (each live key's cap or its month's spend, whichever is more, plus revoked keys'
		spend: what a raise is checked against) against `spend_limit`; `max_keys`; `suspended`.
		`keys`: the team's keys, newest first, masked, each with its cap, this month's spend and effective
		rate limits. `usage`: this month across every key, as `get_usage` answers it."""
		return self.call("grove.api.usage.figures", team=team)

	def pull_usage(self, team: str) -> dict:
		"""Ask Grove to pull the team's usage from its gateways now. Grove allows 2 an hour per
		team, then refuses. → {"sync": the run that logged it, or None when there was nothing to
		pull, "figures": the team's figures read afresh after it}."""
		return self.call("grove.api.usage.pull_usage", team=team)

	def get_usage(
		self,
		teams: list[str],
		month: str | None = None,
		period: str | None = None,
		key_hash: str | None = None,
		pulled_after: str | None = None,
		pulled_until: str | None = None,
	) -> dict:
		"""Requests and cost per team and model over a UTC `month` or `period`, or, for an invoice,
		over a landing window: what Grove pulled between `pulled_after` and `pulled_until` (RFC 3339
		UTC, until exclusive) whatever day it was served on. Central converts its own invoice period
		to UTC before asking."""
		return self.call(
			"grove.api.usage.usage",
			teams=teams,
			month=month,
			period=period,
			key_hash=key_hash,
			pulled_after=pulled_after,
			pulled_until=pulled_until,
		)

	def call(self, method: str, **body) -> dict | list:
		try:
			response = requests.post(
				f"{self.base_url}/api/method/{method}", json=body, headers=self.headers, timeout=TIMEOUT
			)
		except (requests.ConnectionError, requests.Timeout) as e:
			raise GroveUnavailable(_("Grove can't be reached right now.")) from e
		return read(response)


def read(response: requests.Response) -> dict | list:
	if response.status_code in UNAVAILABLE:
		raise GroveUnavailable(_("Grove is unavailable ({0}).").format(response.status_code))
	if response.status_code >= 400:
		message = refusal_message(response)
		if message:
			frappe.throw(message)
		detail = f"{response.status_code}: {response.text[:2000]}"
		frappe.log_error(title="Grove request failed", message=detail)
		if user_has_operator_bypass():
			frappe.throw(_("Grove request failed ({0})").format(detail[:200]))
		frappe.throw(_("The AI service could not complete the request. Try again later."))
	return response.json().get("message", {})


def refusal_message(response: requests.Response) -> str | None:
	"""Grove's own sentence from a refusal, so a person reads why: the first of Frappe's
	`_server_messages`, else its `exception` line. None when the body is not Frappe's."""
	try:
		body = response.json()
		messages = [
			json.loads(raw).get("message") for raw in json.loads(body.get("_server_messages") or "[]")
		]
	except (ValueError, TypeError, AttributeError):
		return None
	return next((message for message in messages if message), None) or body.get("exception")
