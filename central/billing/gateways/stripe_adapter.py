# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Stripe GatewayAdapter.

The only module that imports the `stripe` SDK. Gateway knowledge (Payment
Intents, refunds, webhook signature verification) is ported from the working
press implementation; the structure is the new adapter model.
"""

from typing import ClassVar

import frappe
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


def _country_code(value) -> str | None:
	"""Resolve a Billing Profile country (free-text Data) to an ISO 3166-1 alpha-2
	code, which is what Stripe's address.country expects. Accepts a code already."""
	if not value:
		return None
	v = str(value).strip()
	if len(v) == 2:
		return v.upper()
	code = frappe.db.get_value("Country", v, "code")
	return code.upper() if code else None


def _export_shipping(team: str | None) -> dict | None:
	"""India-exports compliance: a Stripe account based in India must send the
	customer's name + address on every export (international) charge. We source it
	from the team's Billing Profile — which is required complete before any money
	moves — and pass it as a PaymentIntent `shipping` block."""
	if not team:
		return None
	bp = frappe.db.get_value(
		"Billing Profile",
		team,
		["legal_name", "address_line1", "address_line2", "city", "state", "country", "pincode"],
		as_dict=True,
	)
	if not bp or not bp.address_line1:
		return None
	return {
		"name": bp.legal_name or team,
		"address": {
			"line1": bp.address_line1,
			"line2": bp.address_line2 or None,
			"city": bp.city,
			"state": bp.state,
			"postal_code": bp.pincode,
			"country": _country_code(bp.country),
		},
	}


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
	conf_keys: ClassVar[dict[str, str]] = {
		"api_secret": "stripe_secret_key",
		"api_key": "stripe_publishable_key",
		"webhook_secret": "stripe_webhook_secret",
	}

	# Off-session PaymentIntents charge any amount without re-auth (ADR 0005) —
	# the saved-method / postpaid rail. No silent ceiling.
	supports_off_session_charge = True
	max_silent_charge = None

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
		endpoint = _to_dict(
			stripe.WebhookEndpoint.create(
				url=callback_url,
				enabled_events=events or STRIPE_WEBHOOK_EVENTS,
			)
		)
		return {"endpoint_id": endpoint.get("id"), "secret": endpoint.get("secret")}

	def setup_payment_method(self, team, setup_data: dict) -> dict:
		"""Create an off-session SetupIntent; UI confirms it with the card."""
		self._configure()
		intent = _to_dict(
			stripe.SetupIntent.create(
				customer=setup_data.get("customer_id"),
				payment_method_types=["card"],
				usage="off_session",
			)
		)
		return {"client_secret": intent.get("client_secret"), "setup_intent_id": intent.get("id")}

	def validate_payment_method(self, payment_method) -> bool:
		"""Micro-charge (50 minor units) + auto-refund to prove the card is live."""
		self._configure()
		# India-based Stripe accounts require a description AND the customer's
		# name + address on every export (international) charge — Stripe rejects
		# the request otherwise.
		params = dict(
			amount=50,
			currency=(self.default_currency() or "usd").lower(),
			customer=payment_method.get("gateway_customer_id"),
			payment_method=payment_method.gateway_method_id,
			confirm=True,
			off_session=True,
			description="Payment method validation",
		)
		shipping = _export_shipping(payment_method.get("team"))
		if shipping:
			params["shipping"] = shipping
		try:
			intent = _to_dict(stripe.PaymentIntent.create(**params))
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
		amount_minor = round((invoice.amount or 0) * 100)
		# Required for India-account export charges (see validate_payment_method).
		params = dict(
			amount=amount_minor,
			currency=(invoice.currency or "").lower(),
			customer=invoice.get("customer_id"),
			payment_method=payment_method.gateway_method_id,
			off_session=True,
			confirm=True,
			idempotency_key=idempotency_key,
			description=f"Invoice {invoice.get('name') or ''}".strip(),
		)
		shipping = _export_shipping(invoice.get("team") or payment_method.get("team"))
		if shipping:
			params["shipping"] = shipping
		try:
			intent = _to_dict(stripe.PaymentIntent.create(**params))
		except stripe.error.CardError as e:
			body = getattr(e, "json_body", None) or {}
			# `code` for a declined card is almost always "card_declined"; the actual
			# reason (insufficient_funds, lost_card, stolen_card, …) is the decline_code.
			return PaymentResult(
				success=False,
				status="Failed",
				failure_code=getattr(e, "code", None),
				decline_code=(body.get("error") or {}).get("decline_code"),
				failure_reason=getattr(e, "user_message", None) or str(e),
				raw=body,
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
			refund = _to_dict(
				stripe.Refund.create(
					payment_intent=payment_attempt.gateway_transaction_id,
					amount=round((amount or 0) * 100),
				)
			)
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

	def create_order(
		self, amount, currency: str, receipt: str, notes: dict | None = None, customer: str | None = None
	) -> dict:
		"""A PaymentIntent the UI confirms with Stripe.js for a wallet top-up.
		Attaching `customer` lets Stripe save the method on the customer for later
		off-session charges (the same customer id every later charge reuses)."""
		self._configure()
		params = dict(
			amount=round((amount or 0) * 100),
			currency=(currency or "usd").lower(),
			metadata={"receipt": receipt, **(notes or {})},
			# Required for India-account export charges (see validate_payment_method).
			description="Wallet top-up",
		)
		if customer:
			params["customer"] = customer
		# Carry the billing name + address from the team's Billing Profile so an
		# in-app (on-session) top-up clears the same India-export requirement that
		# off-session charge()/validate_payment_method() satisfy — the customer
		# never re-enters an address the profile already holds.
		shipping = _export_shipping((notes or {}).get("team"))
		if shipping:
			params["shipping"] = shipping
		intent = _to_dict(stripe.PaymentIntent.create(**params))
		return {
			"client_secret": intent.get("client_secret"),
			"payment_intent_id": intent.get("id"),
			"amount": intent.get("amount"),
			"publishable_key": self.get_credential("api_key"),
			"currency": (currency or "usd").upper(),
		}

	def get_payment_intent(self, payment_intent_id: str) -> dict:
		"""Retrieve a PaymentIntent so a top-up can be confirmed from what Stripe
		actually charged (status + amount + currency), not a client-supplied figure."""
		self._configure()
		return _to_dict(stripe.PaymentIntent.retrieve(payment_intent_id))

	def create_checkout_session(
		self,
		amount,
		currency: str,
		receipt: str,
		success_url: str,
		cancel_url: str,
		notes: dict | None = None,
		customer: str | None = None,
	) -> dict:
		"""A hosted Stripe Checkout session for a wallet top-up; the UI redirects to
		`checkout_url`. Stripe substitutes {CHECKOUT_SESSION_ID} into success_url.
		Binding `customer` keeps the session under the team's reused customer id."""
		self._configure()
		meta = {"receipt": receipt, **(notes or {})}
		params = dict(
			mode="payment",
			success_url=success_url,
			cancel_url=cancel_url,
			line_items=[
				{
					"quantity": 1,
					"price_data": {
						"currency": (currency or "usd").lower(),
						"unit_amount": round((amount or 0) * 100),
						"product_data": {"name": "Wallet top-up"},
					},
				}
			],
			metadata=meta,
			# description required for India-account export charges (see validate_payment_method).
			payment_intent_data={"metadata": meta, "description": "Wallet top-up"},
		)
		if customer:
			params["customer"] = customer
		session = _to_dict(stripe.checkout.Session.create(**params))
		return {
			"checkout_url": session.get("url"),
			"session_id": session.get("id"),
			"publishable_key": self.get_credential("api_key"),
		}

	def get_checkout_session(self, session_id: str) -> dict:
		self._configure()
		return _to_dict(stripe.checkout.Session.retrieve(session_id))

	def create_setup_checkout_session(self, customer: str, success_url: str, cancel_url: str) -> dict:
		"""A hosted Stripe Checkout session in `setup` mode — the hosted "save a card"
		page (the parallel of the top-up's `payment` mode). Saves the card to the
		team's reused customer; no money moves. The UI redirects to `checkout_url`."""
		self._configure()

		session = _to_dict(
			stripe.checkout.Session.create(
				mode="setup",
				customer=customer,
				payment_method_types=["card"],
				success_url=success_url,
				cancel_url=cancel_url,
			)
		)

		return {"checkout_url": session.get("url"), "session_id": session.get("id")}

	def get_setup_result(self, session_id: str) -> dict:
		"""Read a completed setup Checkout session back to the saved card: the gateway
		payment-method id + card display fields, or `{}` while still pending."""
		self._configure()

		session = _to_dict(stripe.checkout.Session.retrieve(session_id))

		setup_intent_id = session.get("setup_intent")

		if not setup_intent_id:
			return {}

		intent = _to_dict(stripe.SetupIntent.retrieve(setup_intent_id))
		method_id = intent.get("payment_method")

		if intent.get("status") != "succeeded" or not method_id:
			return {}

		card = (_to_dict(stripe.PaymentMethod.retrieve(method_id)).get("card")) or {}

		return {
			"payment_method": method_id,
			"brand": (card.get("brand") or "card").title(),
			"last4": card.get("last4"),
			"exp_month": card.get("exp_month"),
			"exp_year": card.get("exp_year"),
		}

	def create_customer(self, team) -> str:
		self._configure()
		# Team.owner_user is a Link to User, whose name IS the email address.
		customer = _to_dict(
			stripe.Customer.create(
				name=getattr(team, "name", None),
				email=team.get("owner_user") if hasattr(team, "get") else None,
			)
		)
		return customer.get("id")

	def get_mandate_status(self, mandate_reference: str) -> str:
		self._configure()
		return _to_dict(stripe.Mandate.retrieve(mandate_reference)).get("status")
