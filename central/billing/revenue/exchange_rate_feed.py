# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import datetime
from urllib.parse import urlparse

import frappe
import requests

from central.billing.settings import exchange_rate_url

TIMEOUT_SECONDS = 10


def feed_rate(from_currency: str, to_currency: str, day: datetime.date) -> frappe._dict | None:
	"""The rate API's rate for a day, as {rate, rate_date, source}, or None when it gives none."""
	url = exchange_rate_url()
	if not url:
		return None
	try:
		response = requests.get(
			f"{url}/rate/{from_currency}/{to_currency}", params={"date": str(day)}, timeout=TIMEOUT_SECONDS
		)
	except requests.RequestException as error:
		# The caller falls back to an earlier kept rate, so a down API is not an error here.
		frappe.logger("billing").warning(f"Rate API gave no {from_currency} to {to_currency} rate: {error!r}")
		return None
	body = _body(response)
	if not _is_rate_for(body, from_currency, to_currency):
		return None
	return frappe._dict(
		rate=frappe.utils.flt(body["rate"]),
		rate_date=frappe.utils.getdate(body["date"]),
		source=urlparse(url).hostname,
	)


def _body(response) -> dict:
	if response.status_code != 200:
		return {}
	try:
		body = response.json()
	except ValueError:
		return {}
	return body if isinstance(body, dict) else {}


def _is_rate_for(body: dict, from_currency: str, to_currency: str) -> bool:
	date = body.get("date")
	if (body.get("base"), body.get("quote")) != (from_currency, to_currency):
		return False
	if not date or not isinstance(date, str):
		return False
	try:
		frappe.utils.getdate(date)
	except (ValueError, frappe.ValidationError):
		return False
	return frappe.utils.flt(body.get("rate")) > 0
