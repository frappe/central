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

import frappe
import requests

from central.billing.gateways.base import (
	GatewayAdapter,
	GatewayAuthError,
	GatewayError,
	GatewayTimeout,
	NormalisedEvent,
	PaymentResult,
	RefundResult,
	VerifiedPayment,
	header_value,
	token_check,
)

# Network/server failures are transient → GatewayTimeout (retry reuses the key).
_TRANSIENT = (requests.exceptions.RequestException,)

# The only hosts the client secret is ever sent to.
PAYPAL_API_HOSTS = ("https://api-m.paypal.com", "https://api-m.sandbox.paypal.com")

# PayPal answers a repeated PayPal-Request-Id while the first is still running, or after it
# finished, with these. They are not declines: the first request's outcome is unknown here.
_DUPLICATE_ERRORS = {"DUPLICATE_REQUEST_ID", "ORDER_ALREADY_CAPTURED", "PREVIOUS_REQUEST_IN_PROGRESS"}

# A PENDING capture (eCheck, PayPal review) settles within days; the attempt stays open
# until then instead of falling back to another method while PayPal may still take the money.
PENDING_CAPTURE_DAYS = 5

# The events the webhook spine consumes (see webhooks.py).
PAYPAL_WEBHOOK_EVENTS = [
	"PAYMENT.CAPTURE.COMPLETED",
	"PAYMENT.CAPTURE.PENDING",
	"PAYMENT.CAPTURE.DENIED",
	"PAYMENT.CAPTURE.REFUNDED",
	"CUSTOMER.DISPUTE.CREATED",
	"CUSTOMER.DISPUTE.RESOLVED",
]

_DISPUTE_OUTCOMES = {"RESOLVED_BUYER_FAVOUR": "lost", "RESOLVED_SELLER_FAVOUR": "won"}


class PayPalAdapter(GatewayAdapter):
	webhook_events = tuple(PAYPAL_WEBHOOK_EVENTS)

	def _base(self) -> str:
		"""PayPal's sandbox, or the live host when site config `paypal_api_base` names it."""
		base = (frappe.conf.get("paypal_api_base") or PAYPAL_API_HOSTS[1]).rstrip("/")
		if base not in PAYPAL_API_HOSTS:
			raise GatewayError(f"paypal_api_base {base} is not a PayPal host.")
		return base

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
			"setup_intent_id": result.get("id"),
			"approve_url": _link(result, "approve"),
			"customer_id": setup_data.get("customer_id"),
		}

	def read_saved_card(self, setup_reference: str) -> dict:
		"""Turn the setup token the buyer approved into a vault payment token, server-side.
		Keyed on the setup token, so asking twice returns the same payment token."""
		try:
			token = self._create_payment_token(setup_reference)
		except requests.exceptions.HTTPError as e:
			if getattr(e.response, "status_code", None) == 422:
				return {}  # the buyer has not approved it yet
			raise GatewayTimeout(str(e)) from e
		except _TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e
		if not token.get("id"):
			return {}
		email = ((token.get("payment_source") or {}).get("paypal") or {}).get("email_address")
		return {
			"payment_method": token["id"],
			"customer": None,
			"brand": "PayPal",
			"last4": None,
			"label": email,
		}

	def validate_payment_method(self, payment_method) -> PaymentResult:
		"""A live vault token (set on approval) is the proof — no micro-charge."""
		return token_check(payment_method)

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

		status = capture.get("status")
		if status == "PENDING":
			hold = frappe.utils.add_days(frappe.utils.now_datetime(), PENDING_CAPTURE_DAYS)
			return PaymentResult(
				success=False,
				status="Pending",
				gateway_transaction_id=capture.get("id"),
				hold_until=str(hold),
				raw=dict(capture),
			)
		completed = status == "COMPLETED"
		return PaymentResult(
			success=completed,
			status="Captured" if completed else "Failed",
			gateway_transaction_id=capture.get("id"),
			failure_code=capture.get("failure_code"),
			failure_reason=capture.get("failure_reason"),
			raw=dict(capture),
		)

	def refund(
		self, payment_attempt, amount, reason: str, idempotency_key: str | None = None
	) -> RefundResult:
		try:
			refund = self._refund_capture(
				capture_id=payment_attempt.gateway_transaction_id,
				amount=frappe_flt(amount),
				currency=(payment_attempt.get("currency") or "").upper(),
				request_id=idempotency_key
				or f"refund-{payment_attempt.get('name') or payment_attempt.gateway_transaction_id}",
			)
		except _TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e

		status = _REFUND_STATUS.get(refund.get("status"), "Failed")
		return RefundResult(
			success=status != "Failed",
			status=status,
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

	def get_refund_status(self, gateway_refund_id: str) -> str:
		return _REFUND_STATUS.get(self._get_refund(gateway_refund_id).get("status"), "Failed")

	@staticmethod
	def payment_from_event(payload: dict) -> VerifiedPayment | None:
		"""A capture event. Only the order id binds it: the browser can create a PayPal order
		and set its custom_id, so that is never read as our receipt."""
		resource = payload.get("resource") or {}
		event_type = payload.get("event_type") or ""
		if not event_type.startswith("PAYMENT.CAPTURE.") or event_type == "PAYMENT.CAPTURE.REFUNDED":
			return None
		if not resource.get("id"):
			return None
		return VerifiedPayment(
			payment_id=resource["id"],
			captured=resource.get("status") == "COMPLETED",
			amount=frappe_flt(_dig(resource, "amount", "value")),
			currency=str(_dig(resource, "amount", "currency_code") or "").upper(),
			order_id=_dig(resource, "supplementary_data", "related_ids", "order_id"),
		)

	@staticmethod
	def refund_from_event(payload: dict) -> dict | None:
		if payload.get("event_type") != "PAYMENT.CAPTURE.REFUNDED":
			return None
		resource = payload.get("resource") or {}
		return {"id": resource.get("id"), "status": _REFUND_STATUS.get(resource.get("status"), "Failed")}

	@staticmethod
	def dispute_from_event(payload: dict) -> dict | None:
		if not (payload.get("event_type") or "").startswith("CUSTOMER.DISPUTE."):
			return None
		resource = payload.get("resource") or {}
		transactions = resource.get("disputed_transactions") or [{}]
		outcome = _dig(resource, "dispute_outcome", "outcome_code")
		opened = payload.get("event_type") == "CUSTOMER.DISPUTE.CREATED"
		return {
			"id": resource.get("dispute_id"),
			"payment_id": transactions[0].get("seller_transaction_id"),
			"amount": frappe_flt(_dig(resource, "dispute_amount", "value")),
			"reason": resource.get("reason") or "unknown",
			"status": "open" if opened else _DISPUTE_OUTCOMES.get(outcome, resource.get("status")),
		}

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

	def find_order_payment(self, order_id: str) -> VerifiedPayment | None:
		"""The completed capture on an order Central created, or None. An order the payer
		only approved holds no money until Central captures it."""
		capture = _extract_capture(self._get_order(order_id))
		# Without captures, _extract_capture falls back to the order's own id and status.
		if capture.get("status") != "COMPLETED" or capture.get("id") == order_id:
			return None
		return VerifiedPayment(
			payment_id=capture["id"],
			captured=True,
			amount=frappe_flt(capture.get("amount")),
			currency=(capture.get("currency") or "").upper(),
			order_id=order_id,
		)

	def capture_order(self, order_id: str) -> dict:
		"""Capture an approved one-time order; returns {id, status, amount, currency}
		of the capture. `confirm_topup` credits the wallet from this server-confirmed
		amount and stores the capture id as the reconcilable gateway reference."""
		captured = self._capture_order(order_id)
		return _extract_capture(captured)

	# --- gateway I/O (the stubbed seam) -------------------------------------

	def _token(self) -> str:
		"""An OAuth token, cached until shortly before PayPal expires it (about 9 hours)."""
		key = f"paypal_token::{self.gateway.get('name')}"
		if cached := frappe.cache.get_value(key):
			return cached
		resp = requests.post(
			f"{self._base()}/v1/oauth2/token",
			data={"grant_type": "client_credentials"},
			auth=(self.gateway.get_password("api_key"), self.gateway.get_password("api_secret")),
			timeout=30,
		)
		resp.raise_for_status()
		body = resp.json()
		frappe.cache.set_value(
			key, body["access_token"], expires_in_sec=max(int(body.get("expires_in", 0)) - 300, 60)
		)
		return body["access_token"]

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
			if resp.status_code == 409 or body.get("name") in _DUPLICATE_ERRORS:
				raise GatewayTimeout(f"PayPal is still answering request {request_id}: {body.get('name')}")
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

	def _create_payment_token(self, setup_token: str) -> dict:
		resp = requests.post(
			f"{self._base()}/v3/vault/payment-tokens",
			json={"payment_source": {"token": {"id": setup_token, "type": "SETUP_TOKEN"}}},
			headers=self._headers(f"vault-{setup_token}"),
			timeout=30,
		)
		resp.raise_for_status()
		return resp.json()

	def _get_refund(self, refund_id) -> dict:
		resp = requests.get(
			f"{self._base()}/v2/payments/refunds/{refund_id}", headers=self._headers(), timeout=30
		)
		resp.raise_for_status()
		return resp.json()

	def _get_order(self, order_id) -> dict:
		resp = requests.get(
			f"{self._base()}/v2/checkout/orders/{order_id}", headers=self._headers(), timeout=30
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


# A pending refund can still fail, so it is not Completed.
_REFUND_STATUS = {"COMPLETED": "Completed", "PENDING": "Pending", "FAILED": "Failed", "CANCELLED": "Failed"}


def _dig(data: dict, *keys):
	"""A nested value of a PayPal body, or None where any level is missing."""
	for key in keys:
		data = data.get(key) if isinstance(data, dict) else None
	return data


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
