# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Stripe GatewayAdapter.

The only module that imports the `stripe` SDK. Gateway knowledge (Payment
Intents, refunds, webhook signature verification) is ported from the working
press implementation; the structure is the new adapter model.
"""

from contextlib import contextmanager
from typing import ClassVar

import frappe
import stripe

from central.billing.gateways import capabilities
from central.billing.gateways.base import (
	GatewayAdapter,
	GatewayAuthError,
	GatewayError,
	GatewayTimeout,
	NormalisedEvent,
	PaymentResult,
	RefundResult,
	VerifiedPayment,
	WebhookNotFound,
	header_value,
)

# The Stripe API version every request is made with. It matches the stripe-python major
# pinned in pyproject.toml; move both together, and check webhook payloads when you do.
STRIPE_API_VERSION = "2026-08-26.dahlia"

# The events the webhook spine consumes (see webhooks.handle_webhook_event).
STRIPE_WEBHOOK_EVENTS = (
	"payment_intent.succeeded",
	"payment_intent.payment_failed",
	# An authorisation Stripe cancels, for example one that expired uncaptured.
	"payment_intent.canceled",
	"payment_intent.amount_capturable_updated",
	# Recorded only; refunds made outside Central are not applied yet.
	"charge.refunded",
	# A pending refund finishing, or failing after it was accepted.
	"charge.refund.updated",
	"refund.failed",
	"charge.dispute.created",
	"charge.dispute.closed",
	# An Indian mandate the customer or their bank revokes — the card stays valid,
	# the permission to debit it does not.
	"mandate.updated",
	"payment_method.detached",
	# Recorded on the card only. The customer can retry on the same SetupIntent, so
	# one failed try does not fail the card.
	"setup_intent.setup_failed",
)


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


def _predebit_hold(intent: dict) -> str | None:
	"""When an India mandate charge will actually be attempted.

	Confirming the intent is what triggers the bank's pre-debit notification, and
	Stripe then holds it in `processing` for 26 hours (its own buffer over the RBI's
	24) before taking the money. That is a deliberate wait, not a stuck charge, so
	the deadline comes from the intent rather than from a clock of ours.
	"""
	if intent.get("status") != "processing":
		return None
	processing = intent.get("processing") or {}
	notification = (processing.get("card") or {}).get("customer_notification") or {}
	completes_at = notification.get("completes_at")
	if not completes_at:
		return None
	return str(frappe.utils.get_datetime_str(frappe.utils.datetime.datetime.fromtimestamp(completes_at)))


# Stripe may or may not have acted (a network fault, a 5xx, a rate limit, or our own key
# being wrong): the attempt stays open and a retry with the same key finds out.
_UNKNOWN_OUTCOME = (
	stripe.error.APIConnectionError,
	stripe.error.RateLimitError,
	stripe.error.APIError,
	stripe.error.AuthenticationError,
	stripe.error.PermissionError,
)
# Stripe refused the request itself; repeating it will not change the answer.
_INVALID_REQUEST = (stripe.error.InvalidRequestError, stripe.error.IdempotencyError)

# A pending refund (or one waiting on the customer) can still fail, so it is not Completed.
_REFUND_STATUS = {
	"succeeded": "Completed",
	"pending": "Pending",
	"requires_action": "Pending",
	"failed": "Failed",
	"canceled": "Failed",
}


def _verified(intent: dict) -> VerifiedPayment:
	"""A PaymentIntent, read back as what Stripe says was paid. Its metadata is set
	only with our secret key, so its `receipt` is ours."""
	return VerifiedPayment(
		payment_id=intent.get("id"),
		captured=intent.get("status") == "succeeded",
		amount=frappe.utils.flt(intent.get("amount_received") or 0) / 100,
		currency=(intent.get("currency") or "").upper(),
		order_id=intent.get("id"),
		receipt=(intent.get("metadata") or {}).get("receipt"),
	)


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

	# Off-session PaymentIntents are the saved-method rail in every currency
	# (ADR 0022). They charge without re-auth up to the ceiling on the gateway's
	# currency row: none in USD, ₹15,000 in INR, where Stripe India is bound by the
	# same RBI rule as anyone else.
	supports_off_session_charge = True

	webhook_events = STRIPE_WEBHOOK_EVENTS

	def _configure(self):
		# https://docs.stripe.com/rate-limits#object-lock-timeouts
		stripe.max_network_retries = 2
		return stripe

	def _options(self) -> dict:
		"""Per-request key and API version. A module-global key would be shared by every
		Stripe gateway and every thread in the worker."""
		return {"api_key": self.get_credential("api_secret"), "stripe_version": STRIPE_API_VERSION}

	def validate_credentials(self) -> dict:
		"""Cheapest authed read — retrieve the account the secret key belongs to."""
		self._configure()
		try:
			account = _to_dict(stripe.Account.retrieve(**self._options()))
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
		with _stripe_errors():
			endpoint = _to_dict(
				stripe.WebhookEndpoint.create(
					url=callback_url,
					enabled_events=list(events or STRIPE_WEBHOOK_EVENTS),
					**self._options(),
				)
			)
		return {"endpoint_id": endpoint.get("id"), "secret": endpoint.get("secret")}

	def get_webhook(self, endpoint_id: str) -> dict:
		"""Read the endpoint. Keys for another account, or another mode, cannot see it."""
		self._configure()
		with _stripe_errors():
			try:
				endpoint = _to_dict(stripe.WebhookEndpoint.retrieve(endpoint_id, **self._options()))
			except stripe.error.InvalidRequestError as e:
				if getattr(e, "code", None) == "resource_missing":
					raise WebhookNotFound(endpoint_id) from e
				raise
		return {
			"url": endpoint.get("url"),
			"is_active": endpoint.get("status") == "enabled",
			"events": list(endpoint.get("enabled_events") or []),
		}

	def update_webhook_events(self, endpoint_id: str, callback_url: str, events: list[str]) -> None:
		self._configure()
		with _stripe_errors():
			stripe.WebhookEndpoint.modify(endpoint_id, enabled_events=list(events), **self._options())

	def setup_payment_method(self, team, setup_data: dict) -> dict:
		"""Create an off-session SetupIntent; UI confirms it with the card.

		In a currency where recurring debits are regulated — INR, on our Stripe India
		account — the SetupIntent must also register a **mandate**: the customer
		authenticates once against a stated maximum, and every later debit quotes the
		mandate the bank issued. Without it an off-session charge is refused at
		authorisation, however valid the card. Elsewhere a saved card needs no mandate
		and none is asked for.
		"""
		self._configure()
		params = dict(
			customer=setup_data.get("customer_id"),
			payment_method_types=["card"],
			usage="off_session",
		)
		currency = (setup_data.get("currency") or "").upper()
		if capabilities.is_regulated_currency(currency):
			params["payment_method_options"] = {
				"card": self._india_mandate_options(currency, setup_data.get("max_amount"))
			}
		with _stripe_errors():
			intent = _to_dict(stripe.SetupIntent.create(**params, **self._options()))
		return {"client_secret": intent.get("client_secret"), "setup_intent_id": intent.get("id")}

	def _india_mandate_options(self, currency: str, max_amount) -> dict:
		"""India recurring-mandate terms for a SetupIntent.

		`sporadic` is the honest interval: billing is usage-based, so there is no
		fixed amount and no fixed date — we debit when an invoice closes. The stated
		maximum is what the customer consents to, and it is also the number the bank
		enforces, so it is the same ceiling the charge path checks rather than a
		second one that could drift from it.
		"""
		amount = frappe.utils.flt(max_amount) or capabilities.INR_SILENT_CEILING
		return {
			"mandate_options": {
				"reference": frappe.generate_hash(length=12),
				"amount": round(amount * 100),
				"amount_type": "maximum",
				"currency": currency.lower(),
				"interval": "sporadic",
				"supported_types": ["india"],
				"start_date": int(frappe.utils.now_datetime().timestamp()),
				"description": "Frappe Cloud usage billing",
			}
		}

	def validate_payment_method(self, payment_method) -> PaymentResult:
		"""Prove the card is live: by its India mandate, or by a 50-unit charge that is
		refunded at once."""
		self._configure()
		mandate = payment_method.get("gateway_mandate_id")
		if mandate:
			return self._check_mandate(mandate)
		return self._check_with_charge(payment_method)

	def _check_mandate(self, mandate: str) -> PaymentResult:
		"""A debit on an India mandate waits 26 hours for the bank's pre-debit notice, so a
		check charge cannot finish while the customer waits. The customer authenticated the
		mandate at setup, and Stripe keeps it live only while the bank honours it."""
		try:
			status = (self.get_mandate_status(mandate) or "").lower()
		except stripe.error.InvalidRequestError as error:
			return _declined(error)
		except (stripe.error.APIConnectionError, stripe.error.RateLimitError) as error:
			raise GatewayTimeout(str(error)) from error

		# A pending mandate is still being registered at the bank; a charge it refuses
		# later retires the card (charges._retire_method_if_mandate_failed).
		if status in ("active", "pending"):
			return PaymentResult(success=True, status="Validated")
		return PaymentResult(
			success=False,
			status="Failed",
			failure_code=f"mandate_{status}",
			failure_reason=f"The card's mandate is {status} at Stripe.",
		)

	def _check_with_charge(self, payment_method) -> PaymentResult:
		"""Charge 50 minor units off-session and refund them."""
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
			# Keyed on the method, so a repeated confirm charges and refunds the card once.
			idempotency_key=f"{frappe.local.site}:card-check:{payment_method.get('name')}",
		)
		shipping = _export_shipping(payment_method.get("team"))
		if shipping:
			params["shipping"] = shipping
		try:
			intent = _to_dict(stripe.PaymentIntent.create(**params, **self._options()))
		except (stripe.error.CardError, *_INVALID_REQUEST) as error:
			return _declined(error)
		except _UNKNOWN_OUTCOME as error:
			raise GatewayTimeout(str(error)) from error

		if intent.get("status") != "succeeded":
			_close_check_charge(intent, self._options())
			return _unfinished_check(intent)
		_refund_check_charge(intent, params["idempotency_key"], self._options())
		return PaymentResult(success=True, status="Validated", gateway_transaction_id=intent.get("id"))

	def charge(self, invoice, payment_method, idempotency_key: str) -> PaymentResult:
		"""Off-session charge of a stored payment method. Idempotent per attempt.

		Declines are returned as a failed PaymentResult (normal billing flow);
		network/timeouts raise GatewayTimeout so the caller retries with the
		SAME idempotency key (Stripe dedupes), never double-charging.
		"""
		self._configure()
		params = _charge_params(invoice, payment_method, idempotency_key)
		try:
			intent = _to_dict(stripe.PaymentIntent.create(**params, **self._options()))
		except (*_UNKNOWN_OUTCOME, stripe.error.IdempotencyError) as e:
			# A reused key means a charge was already sent with it and may have gone through.
			raise GatewayTimeout(str(e)) from e
		except (stripe.error.CardError, *_INVALID_REQUEST) as e:
			# A mandate Stripe refuses mid-billing surfaces here too, as InvalidRequestError.
			return _declined(e)

		succeeded = intent.get("status") == "succeeded"
		return PaymentResult(
			success=succeeded,
			status="Captured" if succeeded else intent.get("status"),
			# An off-session charge the bank wants the customer to confirm ends as
			# requires_action with no error; the status is the reason.
			failure_code=None if succeeded else intent.get("status"),
			gateway_transaction_id=intent.get("id"),
			hold_until=_predebit_hold(intent),
			raw=intent,
		)

	def refund(
		self, payment_attempt, amount, reason: str, idempotency_key: str | None = None
	) -> RefundResult:
		"""Refund a captured charge to source. Symmetric across gateways."""
		self._configure()
		try:
			refund = _to_dict(
				stripe.Refund.create(
					payment_intent=payment_attempt.gateway_transaction_id,
					amount=round((amount or 0) * 100),
					idempotency_key=idempotency_key,
					**self._options(),
				)
			)
		except _UNKNOWN_OUTCOME as e:
			raise GatewayTimeout(str(e)) from e
		except _INVALID_REQUEST as e:
			return RefundResult(success=False, status="Failed", raw=getattr(e, "json_body", None) or {})

		status = _REFUND_STATUS.get(refund.get("status"), "Failed")
		return RefundResult(
			success=status != "Failed",
			status=status,
			gateway_refund_id=refund.get("id"),
			raw=refund,
		)

	def get_refund_status(self, gateway_refund_id: str) -> str:
		"""Completed, Pending or Failed, as Stripe reports the refund now."""
		self._configure()
		with _stripe_errors():
			refund = _to_dict(stripe.Refund.retrieve(gateway_refund_id, **self._options()))
		return _REFUND_STATUS.get(refund.get("status"), "Failed")

	@staticmethod
	def dispute_from_event(payload: dict) -> dict | None:
		obj = (payload.get("data") or {}).get("object") or {}
		if obj.get("object") != "dispute":
			return None
		opened = payload.get("type") == "charge.dispute.created"
		return {
			"id": obj.get("id"),
			"payment_id": obj.get("payment_intent"),
			"amount": frappe.utils.flt(obj.get("amount")) / 100,
			"reason": obj.get("reason") or "unknown",
			"status": "open" if opened else obj.get("status"),
		}

	@staticmethod
	def refund_from_event(payload: dict) -> dict | None:
		obj = (payload.get("data") or {}).get("object") or {}
		if obj.get("object") != "refund":
			return None
		return {"id": obj.get("id"), "status": _REFUND_STATUS.get(obj.get("status"), "Failed")}

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
		return _to_dict(stripe.PaymentIntent.retrieve(gateway_txn_id, **self._options())).get("status")

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
		with _stripe_errors():
			intent = _to_dict(stripe.PaymentIntent.create(**params, **self._options()))
		return {
			"client_secret": intent.get("client_secret"),
			"payment_intent_id": intent.get("id"),
			"amount": intent.get("amount"),
			"publishable_key": self.get_credential("api_key"),
			"currency": (currency or "usd").upper(),
		}

	def verify_payment(self, payment_id: str) -> VerifiedPayment:
		return _verified(self.get_payment_intent(payment_id))

	def find_order_payment(self, order_id: str) -> VerifiedPayment | None:
		"""An in-app order is a PaymentIntent (`pi_`); a hosted one is a Checkout Session (`cs_`)."""
		if order_id.startswith("cs_"):
			return self.checkout_payment(order_id)
		payment = self.verify_payment(order_id)
		return payment if payment.captured else None

	def checkout_payment(self, session_id: str) -> VerifiedPayment | None:
		session = self.get_checkout_session(session_id)
		if session.get("payment_status") != "paid" or not session.get("payment_intent"):
			return None
		return VerifiedPayment(
			payment_id=session["payment_intent"],
			captured=True,
			amount=frappe.utils.flt(session.get("amount_total")) / 100,
			currency=(session.get("currency") or "").upper(),
			order_id=session_id,
			receipt=(session.get("metadata") or {}).get("receipt"),
		)

	@staticmethod
	def payment_from_event(payload: dict) -> VerifiedPayment | None:
		obj = (payload.get("data") or {}).get("object") or {}
		return _verified(obj) if obj.get("object") == "payment_intent" else None

	def get_payment_intent(self, payment_intent_id: str) -> dict:
		"""Retrieve a PaymentIntent so a top-up can be confirmed from what Stripe
		actually charged (status + amount + currency), not a client-supplied figure."""
		self._configure()
		return _to_dict(stripe.PaymentIntent.retrieve(payment_intent_id, **self._options()))

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
		session = _to_dict(stripe.checkout.Session.create(**params, **self._options()))
		return {
			"checkout_url": session.get("url"),
			"session_id": session.get("id"),
			"publishable_key": self.get_credential("api_key"),
		}

	def get_checkout_session(self, session_id: str) -> dict:
		self._configure()
		return _to_dict(stripe.checkout.Session.retrieve(session_id, **self._options()))

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
				**self._options(),
			)
		)

		# Stripe creates the SetupIntent of a setup mode session with the session.
		return {
			"checkout_url": session.get("url"),
			"session_id": session.get("id"),
			"setup_intent_id": session.get("setup_intent"),
		}

	def read_saved_card(self, setup_reference: str) -> dict:
		"""The card a SetupIntent (`seti_`) or a setup Checkout Session (`cs_`) saved, read
		from Stripe: payment method, customer, mandate and display fields. `{}` while the
		customer has not finished, and only `setup_error` when the bank refused the card."""
		self._configure()
		intent_id = setup_reference
		if setup_reference.startswith("cs_"):
			intent_id = _to_dict(stripe.checkout.Session.retrieve(setup_reference, **self._options())).get(
				"setup_intent"
			)
			if not intent_id:
				return {}

		intent = _to_dict(stripe.SetupIntent.retrieve(intent_id, **self._options()))
		method_id = intent.get("payment_method")
		if intent.get("status") != "succeeded" or not method_id:
			return _unfinished_setup(intent)

		card = (_to_dict(stripe.PaymentMethod.retrieve(method_id, **self._options())).get("card")) or {}
		return {
			"payment_method": method_id,
			"customer": intent.get("customer"),
			"mandate": intent.get("mandate"),
			"brand": (card.get("brand") or "card").title(),
			"last4": card.get("last4"),
			"exp_month": card.get("exp_month"),
			"exp_year": card.get("exp_year"),
		}

	def create_customer(self, team) -> str:
		self._configure()
		# Team.owner_user is a Link to User, whose name IS the email address.
		with _stripe_errors():
			customer = _to_dict(
				stripe.Customer.create(
					name=getattr(team, "name", None),
					email=team.get("owner_user") if hasattr(team, "get") else None,
					**self._options(),
				)
			)
		return customer.get("id")

	def get_mandate_status(self, mandate_reference: str) -> str:
		self._configure()
		return _to_dict(stripe.Mandate.retrieve(mandate_reference, **self._options())).get("status")


def _declined(error: stripe.error.StripeError) -> PaymentResult:
	"""A refused charge, with Stripe's reasons. `code` for a declined card is almost always
	"card_declined"; the actual reason (insufficient_funds, lost_card, …) is the decline_code."""
	body = getattr(error, "json_body", None) or {}
	return PaymentResult(
		success=False,
		status="Failed",
		failure_code=getattr(error, "code", None) or type(error).__name__,
		decline_code=(body.get("error") or {}).get("decline_code"),
		failure_reason=getattr(error, "user_message", None) or str(error),
		raw=body,
	)


def _close_check_charge(intent: dict, options: dict) -> None:
	"""Leave nothing open that could capture later. Stripe cannot cancel a charge that is
	processing, so an operator is told to refund it if it settles."""
	if intent.get("status") == "processing":
		frappe.log_error(title=f"Card check charge {intent.get('id')} is processing; refund it if it settles")
		return
	with _stripe_errors():
		stripe.PaymentIntent.cancel(intent.get("id"), **options)


def _refund_check_charge(intent: dict, key: str, options: dict) -> None:
	"""Give the card check charge back. The card is proven either way, so a failed
	refund is told to an operator and does not fail the card."""
	try:
		stripe.Refund.create(payment_intent=intent.get("id"), idempotency_key=f"{key}:refund", **options)
	except stripe.error.StripeError:
		frappe.log_error(title=f"Card check refund failed for {intent.get('id')}")


def _unfinished_check(intent: dict) -> PaymentResult:
	"""A card check charge that did not succeed: waiting on the customer, or held. The
	method fails either way, so the intent status stays in the reason, not the code."""
	error = intent.get("last_payment_error") or {}
	status = intent.get("status")
	return PaymentResult(
		success=False,
		status="Failed",
		gateway_transaction_id=intent.get("id"),
		failure_code=error.get("code") or "check_unfinished",
		decline_code=error.get("decline_code"),
		failure_reason=error.get("message") or f"The card check charge ended as {status}.",
		raw=intent,
	)


def _unfinished_setup(intent: dict) -> dict:
	"""A SetupIntent that saved no card: only `setup_error` when the bank refused the card,
	`{}` while the customer has not finished."""
	error = intent.get("last_setup_error")
	# Stripe leaves a refused SetupIntent open for the customer to try another card.
	if intent.get("status") != "requires_payment_method" or not error:
		return {}

	return {"setup_error": {"failure_code": error.get("code"), "decline_code": error.get("decline_code")}}


@contextmanager
def _stripe_errors():
	"""Raise a Stripe failure as the gateway error core billing understands, so a bad key or an
	outage never reaches the customer as a bare Stripe exception."""
	try:
		yield
	except stripe.error.AuthenticationError as e:
		raise GatewayAuthError(str(e)) from e
	except (stripe.error.APIConnectionError, stripe.error.RateLimitError) as e:
		raise GatewayTimeout(str(e)) from e
	except stripe.error.CardError:
		raise
	except stripe.error.StripeError as e:
		raise GatewayError(str(e)) from e


def _charge_params(invoice, payment_method, idempotency_key: str) -> dict:
	"""The off-session PaymentIntent for an invoice charge."""
	params = dict(
		amount=round((invoice.amount or 0) * 100),
		currency=(invoice.currency or "").lower(),
		customer=invoice.get("customer_id"),
		payment_method=payment_method.gateway_method_id,
		off_session=True,
		confirm=True,
		idempotency_key=idempotency_key,
		description=f"Invoice {invoice.get('name') or ''}".strip(),
	)
	# Required for India-account export charges (see validate_payment_method).
	shipping = _export_shipping(invoice.get("team") or payment_method.get("team"))
	if shipping:
		params["shipping"] = shipping
	# An Indian mandate debit has to quote the mandate the bank issued at setup;
	# the card alone is not authority to charge off-session there.
	mandate = payment_method.get("gateway_mandate_id")
	if mandate:
		params["mandate"] = mandate
	return params
