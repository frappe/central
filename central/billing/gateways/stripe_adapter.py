# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Stripe GatewayAdapter.

The only module that imports the `stripe` SDK. Gateway knowledge (Payment
Intents, refunds, webhook signature verification) is ported from the working
press implementation; the structure is the new adapter model.
"""

import stripe

from central.billing.gateways.base import (
	GatewayAdapter,
	GatewayAuthError,
	GatewayTimeout,
	NormalisedEvent,
	PaymentResult,
	RefundResult,
	header_value,
)

# The charge/refund lifecycle events the webhook spine consumes (see webhooks.py).
STRIPE_WEBHOOK_EVENTS = [
	"payment_intent.succeeded",
	"payment_intent.payment_failed",
	"payment_intent.amount_capturable_updated",
	"charge.refunded",
]


def _to_dict(obj) -> dict:
	"""Normalise a Stripe response to a plain dict. A StripeObject (stripe v15)
	is not a dict and exposes neither `.get()` nor direct `dict()` conversion,
	but does provide `.to_dict()`. Plain dicts / `frappe._dict` (used in tests)
	are dict subclasses and pass straight through — note we can't probe for
	`.to_dict` via hasattr because `frappe._dict` returns None for any missing
	attribute, so we key off the dict type instead."""
	if isinstance(obj, dict):
		return dict(obj)
	return obj.to_dict()


class StripeAdapter(GatewayAdapter):
	# common_site_config.json overrides for live keys (see GatewayAdapter.get_credential).
	conf_keys = {
		"api_secret": "stripe_secret_key",
		"api_key": "stripe_publishable_key",
		"webhook_secret": "stripe_webhook_secret",
	}

	def _configure(self):
		stripe.api_key = self.get_credential("api_secret")
		# https://docs.stripe.com/rate-limits#object-lock-timeouts
		stripe.max_network_retries = 2
		return stripe

	def validate_credentials(self) -> dict:
		"""Cheapest authed read — retrieve the account the secret key belongs to."""
		self._configure()
		try:
			account = _to_dict(stripe.Account.retrieve())
		except stripe.error.AuthenticationError as e:
			raise GatewayAuthError(str(e)) from e
		except (stripe.error.APIConnectionError, stripe.error.RateLimitError) as e:
			raise GatewayTimeout(str(e)) from e
		return {
			"account_id": account.get("id"),
			"currency": (account.get("default_currency") or "").upper() or None,
		}

	def register_webhook(self, callback_url: str, events: list[str] | None = None) -> dict:
		"""Create a Stripe webhook endpoint; Stripe returns the `whsec_…` secret."""
		self._configure()
		endpoint = _to_dict(stripe.WebhookEndpoint.create(
			url=callback_url,
			enabled_events=events or STRIPE_WEBHOOK_EVENTS,
		))
		return {"endpoint_id": endpoint.get("id"), "secret": endpoint.get("secret")}

	def setup_payment_method(self, team, setup_data: dict) -> dict:
		"""Create an off-session SetupIntent; UI confirms it with the card."""
		self._configure()
		intent = _to_dict(stripe.SetupIntent.create(
			customer=setup_data.get("customer_id"),
			payment_method_types=["card"],
			usage="off_session",
		))
		return {"client_secret": intent.get("client_secret"), "setup_intent_id": intent.get("id")}

	def validate_payment_method(self, payment_method) -> bool:
		"""Micro-charge (50 minor units) + auto-refund to prove the card is live."""
		self._configure()
		try:
			intent = _to_dict(stripe.PaymentIntent.create(
				amount=50,
				currency=(self.default_currency() or "usd").lower(),
				customer=payment_method.get("gateway_customer_id"),
				payment_method=payment_method.gateway_method_id,
				confirm=True,
				off_session=True,
			))
		except stripe.error.CardError:
			return False

		if intent.get("status") == "succeeded":
			stripe.Refund.create(payment_intent=intent.get("id"))
			return True
		return False

	def charge(self, invoice, payment_method, idempotency_key: str) -> PaymentResult:
		"""Off-session charge of a stored payment method. Idempotent per attempt.

		Declines are returned as a failed PaymentResult (normal billing flow);
		network/timeouts raise GatewayTimeout so the caller retries with the
		SAME idempotency key (Stripe dedupes), never double-charging.
		"""
		self._configure()
		amount_minor = int(round((invoice.amount or 0) * 100))
		try:
			intent = _to_dict(stripe.PaymentIntent.create(
				amount=amount_minor,
				currency=(invoice.currency or "").lower(),
				customer=invoice.get("customer_id"),
				payment_method=payment_method.gateway_method_id,
				off_session=True,
				confirm=True,
				idempotency_key=idempotency_key,
			))
		except stripe.error.CardError as e:
			return PaymentResult(
				success=False,
				status="Failed",
				failure_code=getattr(e, "code", None),
				failure_reason=getattr(e, "user_message", None) or str(e),
				raw=getattr(e, "json_body", None) or {},
			)
		except (stripe.error.APIConnectionError, stripe.error.RateLimitError) as e:
			raise GatewayTimeout(str(e)) from e

		succeeded = intent.get("status") == "succeeded"
		return PaymentResult(
			success=succeeded,
			status="Captured" if succeeded else intent.get("status"),
			gateway_transaction_id=intent.get("id"),
			raw=intent,
		)

	def refund(self, payment_attempt, amount, reason: str) -> RefundResult:
		"""Refund a captured charge to source. Symmetric across gateways."""
		self._configure()
		try:
			refund = _to_dict(stripe.Refund.create(
				payment_intent=payment_attempt.gateway_transaction_id,
				amount=int(round((amount or 0) * 100)),
			))
		except (stripe.error.APIConnectionError, stripe.error.RateLimitError) as e:
			raise GatewayTimeout(str(e)) from e

		completed = refund.get("status") in ("succeeded", "pending")
		return RefundResult(
			success=completed,
			status="Completed" if completed else refund.get("status"),
			gateway_refund_id=refund.get("id"),
			raw=refund,
		)

	def verify_webhook_signature(self, payload: bytes, headers: dict) -> bool:
		"""HMAC-verify the raw webhook body. No DB writes; first security gate."""
		secret = self.get_credential("webhook_secret")
		signature = header_value(headers, "Stripe-Signature")
		try:
			stripe.Webhook.construct_event(payload, signature, secret)
			return True
		except (ValueError, stripe.error.SignatureVerificationError):
			return False

	def parse_webhook_event(self, payload: dict, headers: dict | None = None) -> NormalisedEvent:
		"""Normalise an already-verified Stripe event dict (id is in the body)."""
		return NormalisedEvent(
			gateway_event_id=payload.get("id"),
			event_type=payload.get("type"),
			payload=payload,
		)

	def get_transaction_status(self, gateway_txn_id: str) -> str:
		self._configure()
		return _to_dict(stripe.PaymentIntent.retrieve(gateway_txn_id)).get("status")

	def create_order(self, amount, currency: str, receipt: str, notes: dict | None = None,
					 customer: str | None = None) -> dict:
		"""A PaymentIntent the UI confirms with Stripe.js for a wallet top-up.
		Attaching `customer` lets Stripe save the method on the customer for later
		off-session charges (the same customer id every later charge reuses)."""
		self._configure()
		params = dict(amount=int(round((amount or 0) * 100)),
			currency=(currency or "usd").lower(), metadata={"receipt": receipt, **(notes or {})})
		if customer:
			params["customer"] = customer
		intent = _to_dict(stripe.PaymentIntent.create(**params))
		return {"client_secret": intent.get("client_secret"), "payment_intent_id": intent.get("id"),
				"amount": intent.get("amount"), "publishable_key": self.get_credential("api_key"),
				"currency": (currency or "usd").upper()}

	def create_checkout_session(self, amount, currency: str, receipt: str,
								success_url: str, cancel_url: str, notes: dict | None = None,
								customer: str | None = None) -> dict:
		"""A hosted Stripe Checkout session for a wallet top-up; the UI redirects to
		`checkout_url`. Stripe substitutes {CHECKOUT_SESSION_ID} into success_url.
		Binding `customer` keeps the session under the team's reused customer id."""
		self._configure()
		meta = {"receipt": receipt, **(notes or {})}
		params = dict(
			mode="payment",
			success_url=success_url,
			cancel_url=cancel_url,
			line_items=[{
				"quantity": 1,
				"price_data": {
					"currency": (currency or "usd").lower(),
					"unit_amount": int(round((amount or 0) * 100)),
					"product_data": {"name": "Wallet top-up"},
				},
			}],
			metadata=meta,
			payment_intent_data={"metadata": meta},
		)
		if customer:
			params["customer"] = customer
		session = _to_dict(stripe.checkout.Session.create(**params))
		return {"checkout_url": session.get("url"), "session_id": session.get("id"),
				"publishable_key": self.get_credential("api_key")}

	def get_checkout_session(self, session_id: str) -> dict:
		self._configure()
		return _to_dict(stripe.checkout.Session.retrieve(session_id))

	def create_customer(self, team) -> str:
		self._configure()
		# Team.owner_user is a Link to User, whose name IS the email address.
		customer = _to_dict(stripe.Customer.create(
			name=getattr(team, "name", None),
			email=team.get("owner_user") if hasattr(team, "get") else None,
		))
		return customer.get("id")

	def get_mandate_status(self, mandate_reference: str) -> str:
		self._configure()
		return _to_dict(stripe.Mandate.retrieve(mandate_reference)).get("status")
