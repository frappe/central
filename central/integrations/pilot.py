from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import frappe
import requests

from central.sso import mint_bench_login

METRICS_CACHE_TTL_SECONDS = 30
PILOT_TIMEOUT_SECONDS = 3


class PilotMonitoringClient:
	"""Read a bench's existing, Central-JWKS-authenticated monitoring endpoints."""

	def __init__(self, gateway_url: str, audience_id: str):
		self.gateway_url = _gateway_url(gateway_url)
		self.token = mint_bench_login(audience_id)

	def get_metrics(self) -> dict:
		return self._get("/api/v1/metrics")

	def get_history(self, window: str = "24h") -> dict:
		return self._get("/api/v1/monitor/history", params={"window": window})

	def get_overview(self) -> dict:
		"""Live snapshot + 24h history in parallel — one token, two round-trips overlapped."""
		with ThreadPoolExecutor(max_workers=2) as pool:
			metrics = pool.submit(self.get_metrics)
			history = pool.submit(self.get_history)
			return {"current": metrics.result(), "history": history.result()}

	def _get(self, path: str, params: dict | None = None) -> dict:
		try:
			response = requests.get(
				f"{self.gateway_url}{path}",
				headers={"Authorization": f"Bearer {self.token}"},
				params=params,
				timeout=PILOT_TIMEOUT_SECONDS,
				allow_redirects=False,
			)
			response.raise_for_status()
			payload = response.json()
		except (requests.RequestException, ValueError) as exc:
			raise PilotMonitoringError from exc
		if not isinstance(payload, dict):
			raise PilotMonitoringError
		return payload


class PilotMonitoringError(Exception):
	"""Pilot is unavailable or returned an unexpected monitoring response."""


def get_cached_monitoring(resource_id: str, gateway_url: str, audience_id: str) -> dict:
	"""Return one server's live snapshot and 24-hour history from a short Central cache."""
	key = f"pilot:monitoring:{resource_id}"
	if cached := frappe.cache.get_value(key):
		return cached

	try:
		payload = PilotMonitoringClient(gateway_url, audience_id).get_overview()
		monitoring = {"available": True, **payload}
	except PilotMonitoringError:
		frappe.log_error(title=f"Pilot monitoring unavailable: {resource_id}")
		monitoring = {"available": False}

	frappe.cache.set_value(key, monitoring, expires_in_sec=METRICS_CACHE_TTL_SECONDS)
	return monitoring


def _gateway_url(value: str) -> str:
	parsed = urlparse(value)
	if parsed.scheme not in {"http", "https"} or not parsed.netloc:
		raise PilotMonitoringError
	return value.rstrip("/")
