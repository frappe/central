# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import ipaddress

import frappe
import requests

# A country rarely changes for an IP, and a stale miss just re-looks-up, so a long
# TTL is safe and lets Redis evict cold entries.
IP_COUNTRY_TTL_SECONDS = 30 * 24 * 60 * 60


def get_country_from_ip(ip: str | None = None) -> str | None:
	"""The country name for `ip`, or for the request IP, or None when it cannot be found.
	Never raises, so callers must handle None."""
	if frappe.flags.in_test:
		return None

	ip = _clean_public_ip(ip or getattr(frappe.local, "request_ip", None))
	if not ip:
		return None

	# Per-IP key with a TTL rather than one ever-growing `ip_country_map` hash: a
	# hash field never expires, so it accreted a row per distinct signup IP forever.
	# Only `set_value` takes a TTL, so the read and the write stay separate here.
	key = _country_cache_key(ip)
	info = frappe.cache.get_value(key)
	if info is None:
		# A failed lookup is not cached, so a rate-limited answer is not pinned for a month.
		info = _lookup_ip(ip)
		if info:
			frappe.cache.set_value(key, info, expires_in_sec=IP_COUNTRY_TTL_SECONDS)

	return (info or {}).get("country")


def warm_country_cache(ip: str | None = None) -> None:
	"""Look up the request's country in a background job when it is not cached yet.

	A signup sends its code a minute or more before its team is created, so the team's
	billing then reads the country from the cache instead of waiting on the lookup."""
	ip = _clean_public_ip(ip or getattr(frappe.local, "request_ip", None))
	if not ip or frappe.cache.get_value(_country_cache_key(ip)) is not None:
		return

	frappe.enqueue(
		"central.geo.get_country_from_ip",
		ip=ip,
		queue="short",
		enqueue_after_commit=True,
		job_id=f"ip-country:{ip}",
		deduplicate=True,
	)


def _country_cache_key(ip: str) -> str:
	return f"ip_country:{ip}"


def _clean_public_ip(raw: str | None) -> str | None:
	"""The canonical form of `raw` when it is a public IP address, otherwise None.
	`request_ip` can come from a client header, so it is validated before it reaches the lookup
	URL or the cache key."""
	if not raw:
		return None

	# An X-Forwarded-For chain is "client, proxy1, proxy2"; the client is first.
	candidate = str(raw).split(",")[0].strip()
	try:
		addr = ipaddress.ip_address(candidate)
	except ValueError:
		return None
	if (
		addr.is_private
		or addr.is_loopback
		or addr.is_reserved
		or addr.is_link_local
		or addr.is_multicast
		or addr.is_unspecified
	):
		return None

	return addr.compressed


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
		data = requests.get(url, timeout=2).json()
		if data.get("status") != "fail":
			return data
	except Exception:
		frappe.log_error(title="IP country lookup failed")

	return {}
