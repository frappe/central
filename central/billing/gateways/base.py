# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""GatewayAdapter — the single seam between core billing and payment gateways.

Core billing never imports a gateway SDK. Each gateway implements this
interface; adding a gateway is one subclass passing the shared contract suite.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import frappe


def header_value(headers: dict, name: str):
	"""Case-insensitive header lookup (werkzeug preserves sent casing)."""
	if not headers:
		return None
	target = name.lower()
	for key, value in headers.items():
		if key.lower() == target:
			return value
	return None


@dataclass
class PaymentResult:
	success: bool
	status: str  # captured / authorised / failed
	gateway_transaction_id: str | None = None
	failure_code: str | None = None
	failure_reason: str | None = None
	raw: dict = field(default_factory=dict)


@dataclass
class RefundResult:
	success: bool
	status: str  # completed / failed
	gateway_refund_id: str | None = None
	raw: dict = field(default_factory=dict)


@dataclass
class NormalisedEvent:
	gateway_event_id: str
	event_type: str
	payload: dict = field(default_factory=dict)


class GatewayError(Exception):
	"""Generic gateway failure that is not a clean decline."""


class GatewayTimeout(GatewayError):
	"""Network/timeout failure. Retry MUST reuse the same idempotency key."""


class GatewayAuthError(GatewayError):
	"""The gateway rejected the credentials (bad/expired API key/secret).

	Distinct from GatewayTimeout (transient) — bad keys never become good on
	retry, so setup is rejected rather than queued.
	"""


class GatewayUnsupported(GatewayError):
	"""The gateway does not support this optional capability."""


class GatewayAdapter(ABC):
	"""One instance per Payment Gateway config row."""

	# Subclasses map their credential field → the common_site_config.json key
	# that overrides it. Lets ops keep live secrets in site config instead of
	# the Payment Gateway doc (DB). Empty = always read from the doc.
	conf_keys: dict[str, str] = {}

	def __init__(self, gateway):
		self.gateway = gateway

	def get_credential(self, field: str) -> str | None:
		"""Resolve a gateway credential, preferring common_site_config.json over
		the Payment Gateway doc. If `conf_keys[field]` is set in site config we use
		that; otherwise fall back to the encrypted password on the gateway doc."""
		conf_key = self.conf_keys.get(field)
		if conf_key:
			value = frappe.conf.get(conf_key)
			if value:
				return value
		return self.gateway.get_password(field)

	# --- gateway setup (universal) ------------------------------------------

	@abstractmethod
	def validate_credentials(self) -> dict:
		"""Prove the configured keys work via the cheapest authenticated read.

		Returns the gateway account identity (at least `account_id`, and
		`currency` where the gateway exposes it) so setup can confirm the keys
		match the expected account. Raises GatewayAuthError on rejected
		credentials; GatewayTimeout on a transient failure. Never moves money.
		"""
		...

	# --- payment method lifecycle (universal) -------------------------------

	@abstractmethod
	def setup_payment_method(self, team, setup_data: dict) -> dict:
		"""Begin adding a payment method (Stripe SetupIntent / Razorpay mandate order).

		Returns the client-side handles (client_secret / order_id + key) the UI
		needs to complete authorisation. No money is moved here.
		"""
		...

	@abstractmethod
	def validate_payment_method(self, payment_method) -> bool:
		"""Prove the method is live (Stripe micro-charge + auto-refund)."""
		...

	# --- charge / refund / webhooks (universal) -----------------------------

	@abstractmethod
	def charge(self, invoice, payment_method, idempotency_key: str) -> PaymentResult: ...

	@abstractmethod
	def refund(self, payment_attempt, amount, reason: str) -> RefundResult: ...

	@abstractmethod
	def verify_webhook_signature(self, payload: bytes, headers: dict) -> bool: ...

	@abstractmethod
	def parse_webhook_event(self, payload: dict, headers: dict | None = None) -> NormalisedEvent: ...

	@abstractmethod
	def get_transaction_status(self, gateway_txn_id: str) -> str: ...

	# --- optional, gateway-specific capabilities ----------------------------
	# Default: unsupported. Implemented only where the gateway has the concept.

	def register_webhook(self, callback_url: str, events: list[str] | None = None) -> dict:
		"""Create the webhook endpoint at the gateway pointed at `callback_url`
		and return `{"endpoint_id", "secret"}` so setup can auto-fill the signing
		secret (no copy-paste from the gateway dashboard). `events` defaults to the
		adapter's required set. Gateways that can't self-register leave this
		unsupported and the admin enters the secret manually."""
		raise GatewayUnsupported(f"{type(self).__name__} does not support register_webhook")

	def create_order(self, amount, currency: str, receipt: str, notes: dict | None = None) -> dict:
		"""Create a one-time checkout order/intent the client UI completes (top-up).
		Returns the client-side handles (order_id + key / client_secret)."""
		raise GatewayUnsupported(f"{type(self).__name__} does not support create_order")

	def create_checkout_session(self, amount, currency: str, receipt: str,
								success_url: str, cancel_url: str, notes: dict | None = None) -> dict:
		"""Create a gateway-hosted checkout the client redirects to (Stripe Checkout).
		Returns `{checkout_url, session_id}`. The wallet is credited only on return,
		after the session is confirmed paid (see get_checkout_session)."""
		raise GatewayUnsupported(f"{type(self).__name__} does not support create_checkout_session")

	def get_checkout_session(self, session_id: str) -> dict:
		"""Retrieve a hosted-checkout session to confirm it was paid (server-side)."""
		raise GatewayUnsupported(f"{type(self).__name__} does not support get_checkout_session")

	def create_customer(self, team) -> str:
		raise GatewayUnsupported(f"{type(self).__name__} does not support create_customer")

	def verify_payment_signature(self, data: dict) -> bool:
		"""Verify a client-side checkout callback signature (distinct from the
		webhook signature). Razorpay only; Stripe confirms via intent status."""
		raise GatewayUnsupported(f"{type(self).__name__} does not support verify_payment_signature")

	def cancel_mandate(self, mandate_reference: str, customer_reference: str | None = None) -> bool:
		raise GatewayUnsupported(f"{type(self).__name__} does not support cancel_mandate")

	def get_mandate_status(self, mandate_reference: str) -> str:
		raise GatewayUnsupported(f"{type(self).__name__} does not support get_mandate_status")
