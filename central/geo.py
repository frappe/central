# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Resolve a request's country from its IP.

Ported from press (`press.utils.get_country_info`): we ask ip-api.com to geolocate
the caller and cache the answer per IP. Used at signup to seed a team's billing
currency from where the user is signing up from.
"""

from __future__ import annotations

import frappe
import requests


def get_country_from_ip(ip: str | None = None) -> str | None:
	"""Country name (e.g. "India") for `ip`, or None when it can't be determined.

	Falls back to the current request's IP. Returns None on any miss — no IP, a
	private/localhost address, a lookup failure, or during tests — so every caller
	must tolerate None (we default the currency in that case). Never raises."""
	if frappe.flags.in_test:
		return None

	ip = ip or getattr(frappe.local, "request_ip", None)
	if not ip:
		return None

	info = frappe.cache().hget("ip_country_map", ip, generator=lambda: _lookup_ip(ip))
	return (info or {}).get("country")


def _lookup_ip(ip: str) -> dict:
	"""Hit ip-api.com for `ip`. Uses the paid `pro` endpoint when an `ip-api-key`
	is configured, otherwise the free endpoint. A failure (network, rate limit, a
	private-range IP) returns {} — the caller treats that as "country unknown"."""
	key = frappe.conf.get("ip-api-key")
	if key:
		url = f"https://pro.ip-api.com/json/{ip}?key={key}&fields=status,country,countryCode"
	else:
		url = f"http://ip-api.com/json/{ip}?fields=status,country,countryCode"

	try:
		data = requests.get(url, timeout=5).json()
		if data.get("status") != "fail":
			return data
	except Exception:
		frappe.log_error(title="IP country lookup failed")
	return {}
