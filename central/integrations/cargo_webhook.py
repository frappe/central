from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import json
from collections.abc import Callable

import frappe
from frappe import _
from frappe.utils.password import get_decrypted_password

SIGNATURE_HEADER = "X-Frappe-Webhook-Signature"


def verify_cargo_webhook(func: Callable) -> Callable:
	"""Authenticates the HMAC over the raw body before the handler runs, stashing the
	verified context on frappe.local. functools.wraps is required -- Frappe maps request
	args off the wrapped signature."""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		frappe.local.cargo_webhook = _authenticate_cargo_webhook(frappe.request.get_data())
		return func(*args, **kwargs)

	return wrapper


def _reject_webhook(reason: str):
	"""Log the specific reason to the Error Log for operators -- repeated rejections mean
	secret drift or a forged caller -- but throw one uniform 403 so a caller cannot probe
	which check failed."""
	frappe.log_error(title="Rejected inbound Cargo webhook", message=reason)

	# Uniform 403. Don't set http_status_code -- Frappe's exception handler overrides it.
	frappe.throw(_("Invalid webhook signature."), frappe.PermissionError)


def _reported_region(raw_body: bytes) -> str | None:
	"""The region a report names. A body that is not the JSON object Cargo sends names none."""
	try:
		reported = json.loads(raw_body or b"")
	except ValueError:
		return None

	return reported.get("region") if isinstance(reported, dict) else None


def signature_matches(secret: str, raw_body: bytes, signature: str) -> bool:
	"""Constant-time check of Frappe's webhook signature: base64 of an HMAC-SHA256 over the
	body exactly as it was sent, which is why the raw bytes are signed rather than a reparse."""
	expected = base64.b64encode(hmac.new(secret.encode(), raw_body, hashlib.sha256).digest())

	return hmac.compare_digest(expected, signature.encode())


def _authenticate_cargo_webhook(raw_body: bytes) -> frappe._dict:
	"""Authenticate an inbound report and return its verified context.

	The region in the body only selects which secret to check, never trusted on its own;
	every failure throws the same generic message."""
	signature = frappe.get_request_header(SIGNATURE_HEADER)
	if not signature:
		_reject_webhook("missing signature header")

	region = _reported_region(raw_body)
	if not region:
		_reject_webhook("no region in the report")

	instance = frappe.db.get_value("Cargo Instance", {"region": region, "status": ["!=", "Disabled"]})
	if not instance:
		_reject_webhook(f"unknown or disabled region '{region}'")

	secret = get_decrypted_password("Cargo Instance", instance, "webhook_secret", raise_exception=False)
	if not secret:
		_reject_webhook(f"no webhook secret for region '{region}'")

	if not signature_matches(secret, raw_body, signature):
		_reject_webhook(f"signature mismatch for region '{region}'")

	return frappe._dict(instance=instance, region=region, raw=raw_body)
