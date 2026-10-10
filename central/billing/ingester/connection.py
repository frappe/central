# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""HTTP client for the accounting system that keeps the statutory records."""

import json
from urllib.parse import quote

import frappe
import requests

TIMEOUT_SECONDS = 30


class NoAccess(Exception):
	"""The accounting sync user may not read this record."""


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


def call(method: str, params: dict | None = None) -> dict | None:
	"""GET a whitelisted method and return its whole response body."""
	if not enabled():
		return None
	response = requests.get(
		_url(f"api/method/{method}"), params=params, headers=auth_headers(), timeout=TIMEOUT_SECONDS
	)
	response.raise_for_status()
	return response.json()


def fetch(doctype: str, name: str) -> frappe._dict | None:
	"""One record by name, or None when it does not exist."""
	if not enabled():
		return None
	response = requests.get(
		_url(f"api/resource/{quote(doctype)}/{quote(name, safe='')}"),
		headers=auth_headers(),
		timeout=TIMEOUT_SECONDS,
	)
	if response.status_code == 404:
		return None
	if response.status_code == 403:
		raise NoAccess(f"{doctype} {name}")
	response.raise_for_status()
	return frappe._dict(response.json().get("data") or {})


def print_pdf(doctype: str, name: str, print_format: str, letterhead: str | None = None) -> bytes:
	"""A document as a PDF, rendered by the accounting system's Chromium print generator."""
	return download(
		"frappe.utils.print_format_generator.download_pdf",
		{
			"doctype": doctype,
			"name": name,
			"print_format": print_format,
			"letterhead": letterhead or "No Letterhead",
		},
	)


def download(method: str, params: dict) -> bytes:
	"""GET a whitelisted method that answers with a file, and return its bytes."""
	response = requests.get(
		_url(f"api/method/{method}"), params=params, headers=auth_headers(), timeout=TIMEOUT_SECONDS
	)
	response.raise_for_status()
	return response.content


def find(doctype: str, filters: list, fields: list | None = None) -> list[frappe._dict]:
	"""Records matching `filters`, as a list."""
	rows = _request_list(
		f"api/resource/{quote(doctype)}",
		params={
			"filters": json.dumps(filters),
			"fields": json.dumps(fields or ["name"]),
			"limit_page_length": 0,
		},
	)
	return [frappe._dict(row) for row in rows or []]


def _request_list(endpoint: str, **kwargs) -> list | None:
	if not enabled():
		return None
	response = requests.get(_url(endpoint), headers=auth_headers(), timeout=TIMEOUT_SECONDS, **kwargs)
	response.raise_for_status()
	return response.json().get("data") or []


def _request(method: str, endpoint: str, **kwargs) -> frappe._dict | None:
	"""Send one request and return its `data` or `message`. None when sync is off."""
	if not enabled():
		return None
	response = requests.request(
		method, _url(endpoint), headers=auth_headers(), timeout=TIMEOUT_SECONDS, **kwargs
	)
	response.raise_for_status()
	body = response.json()
	value = body.get("data") or body.get("message")
	if value is None or isinstance(value, dict):
		return frappe._dict(value or {})
	return value  # a method may answer with a string or a list


def _url(endpoint: str) -> str:
	base = (frappe.conf.get("erpnext_url") or "").rstrip("/")
	if not base:
		raise RuntimeError("erpnext_url is not set in the site config")
	return f"{base}/{endpoint.lstrip('/')}"
