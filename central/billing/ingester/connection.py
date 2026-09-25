# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""HTTP client for the accounting system that keeps the statutory records."""

import frappe
import requests

TIMEOUT_SECONDS = 30


def enabled() -> bool:
	"""Whether this site pushes records to the accounting system at all."""
	return bool(frappe.conf.get("enable_erpnext_sync"))


def auth_headers() -> dict:
	key = frappe.conf.get("erpnext_api_key")
	secret = frappe.conf.get("erpnext_api_secret")
	if key and secret:
		return {"Authorization": f"token {key}:{secret}"}
	return {}


def get(endpoint: str, params: dict | None = None) -> frappe._dict | None:
	return _request("GET", endpoint, params=params)


def post(endpoint: str, payload: dict) -> frappe._dict | None:
	return _request("POST", endpoint, json=payload)


def put(endpoint: str, payload: dict) -> frappe._dict | None:
	return _request("PUT", endpoint, json=payload)


def _request(method: str, endpoint: str, **kwargs) -> frappe._dict | None:
	"""Send one request and return its `data` or `message`. None when sync is off."""
	if not enabled():
		return None
	response = requests.request(
		method, _url(endpoint), headers=auth_headers(), timeout=TIMEOUT_SECONDS, **kwargs
	)
	response.raise_for_status()
	body = response.json()
	return frappe._dict(body.get("data") or body.get("message") or {})


def _url(endpoint: str) -> str:
	base = (frappe.conf.get("erpnext_url") or "").rstrip("/")
	if not base:
		raise RuntimeError("erpnext_url is not set in the site config")
	return f"{base}/{endpoint.lstrip('/')}"
