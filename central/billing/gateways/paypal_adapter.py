# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""PayPal GatewayAdapter.

Implemented directly against PayPal's REST API over `requests` rather than a
vendored SDK — adding a gateway is one adapter class, no core changes, and no
fragile SDK dependency. All gateway I/O goes through small private methods
(`_token`, `_capture_payment`, `_refund_capture`, ...), which is the seam tests
stub — exactly as the Stripe/Razorpay adapters stub their SDK client.
"""

import json

import requests

from central.billing.gateways.base import (
	GatewayAdapter,
	GatewayAuthError,
	GatewayTimeout,
	NormalisedEvent,
	PaymentResult,
	RefundResult,
	header_value,
)

# Network/server failures are transient → GatewayTimeout (retry reuses the key).
_TRANSIENT = (requests.exceptions.RequestException,)

# The charge lifecycle events the webhook spine consumes (see webhooks.py).
PAYPAL_WEBHOOK_EVENTS = [
	"PAYMENT.CAPTURE.COMPLETED",
	"PAYMENT.CAPTURE.DENIED",
	"PAYMENT.CAPTURE.REFUNDED",
]


class PayPalAdapter(GatewayAdapter):
	def _base(self) -> str:
		return (self.gateway.get("api_base") if hasattr(self.gateway, "get") else None) or (
			"https://api-m.sandbox.paypal.com"
		)

	# --- universal -----------------------------------------------------------

	def validate_credentials(self) -> dict:
		"""Cheapest authed read — fetch an OAuth token; bad client id/secret 401s.

		PayPal does not expose a settlement currency on the OAuth response, so
		`currency` is left None (no currency cross-check for PayPal)."""
		try:
			self._token()
		except requests.exceptions.HTTPError as e:
			status = getattr(e.response, "status_code", None)
			if status in (400, 401):
				raise GatewayAuthError(str(e)) from e
			raise GatewayTimeout(str(e)) from e
		except _TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e
		return {"account_id": self.gateway.get_password("api_key"), "currency": None}

	def register_webhook(self, callback_url: str, events: list[str] | None = None) -> dict:
		"""Create a PayPal webhook. PayPal verifies callbacks by webhook *id* (not a
		signing secret), so the id is what `webhook_secret` stores — return it as
		both endpoint_id and secret."""
		webhook = self._create_webhook(callback_url, events or PAYPAL_WEBHOOK_EVENTS)
		webhook_id = webhook.get("id")
		return {"endpoint_id": webhook_id, "secret": webhook_id}

	def setup_payment_method(self, team, setup_data: dict) -> dict:
		"""Begin vaulting a PayPal payment method (a Vault setup token the buyer
		approves). Returns the approve link + token id; no money is moved."""
		result = self._create_setup_token(team, setup_data)
		return {
			"setup_token_id": result.get("id"),
			"approve_url": _link(result, "approve"),
			"customer_id": setup_data.get("customer_id"),
		}

	def validate_payment_method(self, payment_method) -> bool:
		"""A live vault token (set on approval) is the proof — no micro-charge."""
		return bool(payment_method.gateway_method_id)

	def charge(self, invoice, payment_method, idempotency_key: str) -> PaymentResult:
		"""Off-session capture against a vaulted token. `idempotency_key` rides
		the `PayPal-Request-Id` header so a retry never double-charges."""
		amount = frappe_flt(invoice.get("amount"))
		currency = (invoice.get("currency") or "").upper()
		try:
			capture = self._capture_payment(
				vault_token=payment_method.gateway_method_id,
				amount=amount,
				currency=currency,
				request_id=idempotency_key,
			)
		except _TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e

		completed = capture.get("status") == "COMPLETED"
		return PaymentResult(
			success=completed,
			status="Captured" if completed else "Failed",
			gateway_transaction_id=capture.get("id"),
			failure_code=capture.get("failure_code"),
			failure_reason=capture.get("failure_reason"),
			raw=dict(capture),
		)

	def refund(self, payment_attempt, amount, reason: str) -> RefundResult:
		try:
			refund = self._refund_capture(
				capture_id=payment_attempt.gateway_transaction_id,
				amount=frappe_flt(amount),
				currency=(payment_attempt.get("currency") or "").upper(),
				request_id=f"refund-{payment_attempt.get('name') or payment_attempt.gateway_transaction_id}",
			)
		except _TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e

		done = refund.get("status") in ("COMPLETED", "PENDING")
		return RefundResult(
			success=done,
			status="Completed" if done else refund.get("status"),
			gateway_refund_id=refund.get("id"),
			raw=dict(refund),
		)

	def verify_webhook_signature(self, payload: bytes, headers: dict) -> bool:
		"""Verify via PayPal's verify-webhook-signature API (first security gate)."""
		try:
			return self._verify_webhook(payload, headers)
		except _TRANSIENT:
			return False

	def parse_webhook_event(self, payload: dict, headers: dict | None = None) -> NormalisedEvent:
		"""PayPal carries the event id + type in the body."""
		return NormalisedEvent(
			gateway_event_id=payload.get("id"),
			event_type=payload.get("event_type"),
			payload=payload,
		)

	def get_transaction_status(self, gateway_txn_id: str) -> str:
		return self._get_capture(gateway_txn_id).get("status")

	# --- optional ------------------------------------------------------------

	def create_customer(self, team) -> str:
		# PayPal vaults against the buyer's account; a separate customer object is
		# not required. Surface the team key as the local customer reference.
		return getattr(team, "name", None) or (team.get("name") if hasattr(team, "get") else None)

	# --- on-session one-time top-up -----------------------------------------

	def create_order(
		self, amount, currency: str, receipt: str, notes: dict | None = None, customer: str | None = None
	) -> dict:
		"""A one-time CAPTURE-intent PayPal Order for a wallet top-up. The SPA renders
		PayPal Buttons against `order_id` (client_id is the public client identifier);
		`confirm_topup` captures it server-side. PayPal settles us directly, so the
		capture id (set at capture) is the reference Finance reconciles against."""
		order = self._create_order(amount, (currency or "").upper(), receipt, notes or {})
		return {
			"order_id": order.get("id"),
			"approve_url": _link(order, "approve"),
			# PayPal's client id is public (it ships in the browser SDK), unlike the secret.
			"client_id": self.gateway.get_password("api_key"),
		}

	def capture_order(self, order_id: str) -> dict:
		"""Capture an approved one-time order; returns {id, status, amount, currency}
		of the capture. `confirm_topup` credits the wallet from this server-confirmed
		amount and stores the capture id as the reconcilable gateway reference."""
		captured = self._capture_order(order_id)
		return _extract_capture(captured)

	# --- gateway I/O (the stubbed seam) -------------------------------------

	def _token(self) -> str:
		resp = requests.post(
			f"{self._base()}/v1/oauth2/token",
			data={"grant_type": "client_credentials"},
			auth=(self.gateway.get_password("api_key"), self.gateway.get_password("api_secret")),
			timeout=30,
		)
		resp.raise_for_status()
		return resp.json()["access_token"]

	def _headers(self, request_id: str | None = None) -> dict:
		headers = {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}
		if request_id:
			headers["PayPal-Request-Id"] = request_id
		return headers

	def _create_webhook(self, callback_url: str, events: list[str]) -> dict:
		resp = requests.post(
			f"{self._base()}/v1/notifications/webhooks",
			json={
				"url": callback_url,
				"event_types": [{"name": name} for name in events],
			},
			headers=self._headers(),
			timeout=30,
		)
		resp.raise_for_status()
		return resp.json()

	def _create_setup_token(self, team, setup_data: dict) -> dict:
		resp = requests.post(
			f"{self._base()}/v3/vault/setup-tokens",
			json={"payment_source": setup_data.get("payment_source", {"paypal": {}})},
			headers=self._headers(),
			timeout=30,
		)
		resp.raise_for_status()
		return resp.json()

	def _create_order(self, amount, currency, receipt, notes) -> dict:
		resp = requests.post(
			f"{self._base()}/v2/checkout/orders",
			json={
				"intent": "CAPTURE",
				"purchase_units": [
					{
						"amount": {"currency_code": currency, "value": f"{amount:.2f}"},
						"custom_id": receipt,
					}
				],
			},
			headers=self._headers(receipt),
			timeout=30,
		)
		resp.raise_for_status()
		return resp.json()

	def _capture_order(self, order_id) -> dict:
		resp = requests.post(
			f"{self._base()}/v2/checkout/orders/{order_id}/capture",
			headers=self._headers(),
			timeout=30,
		)
		resp.raise_for_status()
		return resp.json()

	def _capture_payment(self, vault_token, amount, currency, request_id) -> dict:
		"""Create a CAPTURE-intent order against the vault token and return the
		capture. A 4xx instrument decline is normalised to a non-COMPLETED status
		(a clean decline, not an exception); network/5xx propagate as transient."""
		resp = requests.post(
			f"{self._base()}/v2/checkout/orders",
			json={
				"intent": "CAPTURE",
				"purchase_units": [{"amount": {"currency_code": currency, "value": f"{amount:.2f}"}}],
				"payment_source": {"token": {"id": vault_token, "type": "PAYMENT_METHOD_TOKEN"}},
			},
			headers=self._headers(request_id),
			timeout=30,
		)
		if 400 <= resp.status_code < 500:
			body = _safe_json(resp)
			return {
				"id": None,
				"status": "DECLINED",
				"failure_code": body.get("name"),
				"failure_reason": body.get("message"),
			}
		resp.raise_for_status()
		return _extract_capture(resp.json())

	def _refund_capture(self, capture_id, amount, currency, request_id) -> dict:
		resp = requests.post(
			f"{self._base()}/v2/payments/captures/{capture_id}/refund",
			json={"amount": {"value": f"{amount:.2f}", "currency_code": currency}},
			headers=self._headers(request_id),
			timeout=30,
		)
		resp.raise_for_status()
		return resp.json()

	def _get_capture(self, capture_id) -> dict:
		resp = requests.get(
			f"{self._base()}/v2/payments/captures/{capture_id}", headers=self._headers(), timeout=30
		)
		resp.raise_for_status()
		return resp.json()

	def _verify_webhook(self, payload: bytes, headers: dict) -> bool:
		body = payload.decode() if isinstance(payload, bytes) else payload
		resp = requests.post(
			f"{self._base()}/v1/notifications/verify-webhook-signature",
			json={
				"auth_algo": header_value(headers, "PAYPAL-AUTH-ALGO"),
				"cert_url": header_value(headers, "PAYPAL-CERT-URL"),
				"transmission_id": header_value(headers, "PAYPAL-TRANSMISSION-ID"),
				"transmission_sig": header_value(headers, "PAYPAL-TRANSMISSION-SIG"),
				"transmission_time": header_value(headers, "PAYPAL-TRANSMISSION-TIME"),
				"webhook_id": self.gateway.get_password("webhook_secret"),
				"webhook_event": json.loads(body),
			},
			headers=self._headers(),
			timeout=30,
		)
		resp.raise_for_status()
		return resp.json().get("verification_status") == "SUCCESS"


def frappe_flt(value) -> float:
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def _link(doc: dict, rel: str):
	for link in doc.get("links", []) or []:
		if link.get("rel") == rel:
			return link.get("href")
	return None


def _safe_json(resp) -> dict:
	try:
		return resp.json()
	except Exception:
		return {}


def _extract_capture(order: dict) -> dict:
	"""Pull the capture {id, status, amount, currency} out of a captured order."""
	units = order.get("purchase_units") or []
	captures = ((units[0].get("payments") or {}).get("captures") or []) if units else []
	if captures:
		cap = captures[0]
		amt = cap.get("amount") or {}
		return {
			"id": cap.get("id"),
			"status": cap.get("status"),
			"amount": amt.get("value"),
			"currency": amt.get("currency_code"),
		}
	# Fall back to the order's own status when the shape is flatter.
	return {"id": order.get("id"), "status": order.get("status")}
