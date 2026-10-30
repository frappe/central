# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Razorpay GatewayAdapter, one of the modules allowed to import a gateway SDK."""

import hashlib
from typing import ClassVar

import frappe
import razorpay
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
	WebhookNotFound,
	header_value,
	token_check,
)
from central.billing.payments.decline import REQUEST_REFUSED

# Razorpay raises these for transient/server failures; a refused request is BadRequestError.
_TRANSIENT = (razorpay.errors.GatewayError, razorpay.errors.ServerError, requests.exceptions.RequestException)

# Razorpay notifies the payer a day before a recurring debit and takes the money after,
# so a debit stays in progress this long before anyone should ask about it.
RECURRING_HOLD_HOURS = 36

# The events the webhook spine consumes (see webhooks.handle_webhook_event).
RAZORPAY_WEBHOOK_EVENTS = (
	"payment.captured",
	"payment.failed",
	"payment.authorized",
	# A pending refund finishing, or failing after it was accepted.
	"refund.processed",
	"refund.failed",
	"payment.dispute.created",
	"payment.dispute.won",
	"payment.dispute.lost",
	"payment.dispute.closed",
)


class RazorpayAdapter(GatewayAdapter):
	# common_site_config.json overrides for live keys (see GatewayAdapter.get_credential).
	conf_keys: ClassVar[dict[str, str]] = {
		"api_key": "razorpay_key_id",
		"api_secret": "razorpay_key_secret",
		"webhook_secret": "razorpay_webhook_secret",
	}

	# Razorpay pulls UPI Autopay and card mandates off-session. The silent-debit cap and pre-debit
	# notice are set per currency on the gateway row (ADR 0022); the RBI caps INR at ₹15,000 everywhere.
	supports_off_session_charge = True

	webhook_events = RAZORPAY_WEBHOOK_EVENTS

	def _client(self):
		return razorpay.Client(auth=(self.get_credential("api_key"), self.get_credential("api_secret")))

	def validate_credentials(self) -> dict:
		"""List one payment to prove the keys; a BadRequestError means bad keys. Settles in INR."""
		try:
			self._client().payment.all({"count": 1})
		except razorpay.errors.BadRequestError as e:
			raise GatewayAuthError(str(e)) from e
		except _TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e
		return {"account_id": self.get_credential("api_key"), "currency": "INR"}

	def register_webhook(self, callback_url: str, events: list[str] | None = None) -> dict:
		"""Create a webhook with a strong secret made here, as Razorpay takes a caller-chosen one."""
		secret = frappe.generate_hash(length=32)
		# Razorpay wants events as an object {name: 1}, not a list — a list is
		# serialised positionally and the API rejects it ("Invalid event name/names: 1, 2, 3").
		try:
			webhook = self._client().webhook.create(
				{
					"url": callback_url,
					"secret": secret,
					"events": {name: 1 for name in (events or RAZORPAY_WEBHOOK_EVENTS)},
				}
			)
		except razorpay.errors.BadRequestError as e:
			raise GatewayError(str(e)) from e
		except _TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e
		return {"endpoint_id": webhook.get("id"), "secret": secret}

	def get_webhook(self, endpoint_id: str) -> dict:
		"""Read the webhook. The keys are proven, so a refused read means it is not in this account."""
		try:
			webhook = self._client().webhook.fetch(endpoint_id, None)
		except razorpay.errors.BadRequestError as e:
			raise WebhookNotFound(endpoint_id) from e
		except _TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e
		events = webhook.get("events") or []
		# Razorpay returns the events as {name: true} or as a list of names.
		if isinstance(events, dict):
			events = [name for name, enabled in events.items() if enabled]
		return {"url": webhook.get("url"), "is_active": bool(webhook.get("active")), "events": list(events)}

	def update_webhook_events(self, endpoint_id: str, callback_url: str, events: list[str]) -> None:
		try:
			self._client().webhook.edit(
				endpoint_id, None, {"url": callback_url, "events": {name: 1 for name in events}}
			)
		except _TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e

	def setup_payment_method(self, team, setup_data: dict) -> dict:
		"""Create a recurring authorisation order on the `method` rail ("upi" or "card"), with
		`max_amount` as the token's ceiling. The UI runs Checkout against it to get the token."""
		client = self._client()
		method = setup_data.get("method") or "upi"
		max_amount = int(setup_data.get("max_amount") or 0)
		receipt = "Authorize UPI Autopay" if method == "upi" else "Authorize card mandate"
		order = client.order.create(
			{
				"amount": 100,
				"currency": "INR",
				"method": method,
				"customer_id": setup_data.get("customer_id"),
				"receipt": receipt,
				# Auto-capture the registration auth; without it the payment stays
				# "authorized" (manual capture) and Checkout reports the mandate failed.
				"payment_capture": 1,
				"token": {"max_amount": max_amount * 100},
				"notes": {"team": team},
			}
		)
		return {
			"order_id": order.get("id"),
			"customer_id": setup_data.get("customer_id"),
			"key_id": self.get_credential("api_key"),
			# Checkout must run in recurring mode (with the customer_id) for the token
			# to be issued — otherwise it processes a one-time ₹1 charge that fails.
			"recurring": 1,
		}

	def validate_payment_method(self, payment_method) -> PaymentResult:
		"""The mandate authorisation is the validation: a live token is the proof, no micro-charge."""
		return token_check(payment_method)

	def prepare_charge(self, invoice, receipt: str) -> str | None:
		"""The order a recurring charge is made against. Razorpay has no charge idempotency key, so
		the order id, stored before the payment, lets a retry find the payment instead of repeating it."""
		try:
			order = self._client().order.create(
				{
					"amount": round((invoice.amount or 0) * 100),
					"currency": (invoice.currency or "").upper(),
					"receipt": receipt[:40],  # a label for the dashboard, capped by Razorpay
					"payment_capture": 1,  # settle the charge, don't leave it authorized
					"notes": {"invoice": invoice.get("name")},
				}
			)
		except razorpay.errors.BadRequestError as e:
			raise GatewayError(str(e)) from e
		except _TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e
		return order["id"]

	def charge(self, invoice, payment_method, idempotency_key: str) -> PaymentResult:
		"""Off-session recurring charge against a mandate token, on the stored order. A payment the
		order already has is returned rather than repeated (see _settled_or_live)."""
		order_id = invoice.get("order_id")
		if not order_id:
			raise GatewayError("A Razorpay charge needs the order prepare_charge created and Central stored.")
		client = self._client()
		try:
			if earlier := _settled_or_live(_order_payments(client, order_id)):
				return earlier
			# Checked after the order's payments, so a resumed charge returns the payment it made.
			payer = frappe.db.get_value(
				"Billing Profile", payment_method.team, ["email", "phone"], as_dict=True
			)
			if not payer or not payer.email or not payer.phone:
				return _refused(
					f"Billing Profile {payment_method.team} needs an email and a phone to debit a mandate."
				)
			created = client.payment.createRecurring(
				_recurring_charge(invoice, payment_method, order_id, payer)
			)
			# The reply carries only the payment id; the payment itself says how it went.
			payment = client.payment.fetch(created["razorpay_payment_id"])
		except razorpay.errors.BadRequestError as e:
			# A recurring debit is declined later, on `payment.failed`. Refusing to create
			# it means the request itself is wrong, and sending it again changes nothing.
			return _refused(str(e))
		except _TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e
		return _recurring_result(payment)

	def refund(
		self, payment_attempt, amount, reason: str, idempotency_key: str | None = None
	) -> RefundResult:
		"""Refund to the source, with `X-Refund-Idempotency` so a retried refund is not made twice."""
		client = self._client()
		body = {"amount": round((amount or 0) * 100)}
		options = {}
		if idempotency_key:
			body["receipt"] = idempotency_key[:40]
			# The same key and body return the first refund; the SDK passes headers to requests.
			options["headers"] = {"X-Refund-Idempotency": _refund_key(idempotency_key)}
		try:
			refund = client.payment.refund(payment_attempt.gateway_transaction_id, body, **options)
		except _TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e

		status = _REFUND_STATUS.get(refund.get("status"), "Failed")
		return RefundResult(status=status, gateway_refund_id=refund.get("id"), raw=dict(refund))

	def get_refund_status(self, gateway_refund_id: str) -> str:
		"""Completed, Pending or Failed, as Razorpay reports the refund now."""
		try:
			refund = self._client().refund.fetch(gateway_refund_id)
		except _TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e
		return _REFUND_STATUS.get(refund.get("status"), "Failed")

	@staticmethod
	def dispute_from_event(payload: dict) -> dict | None:
		entity = ((payload.get("payload") or {}).get("dispute") or {}).get("entity")
		if not entity:
			return None
		outcome = (payload.get("event") or "").rsplit(".", 1)[-1]
		return {
			"id": entity.get("id"),
			"payment_id": entity.get("payment_id"),
			"amount": frappe.utils.flt(entity.get("amount")) / 100,
			"reason": entity.get("reason_code") or "unknown",
			"status": {"created": "open", "won": "won", "lost": "lost"}.get(outcome, entity.get("status")),
		}

	@staticmethod
	def refund_from_event(payload: dict) -> dict | None:
		entity = ((payload.get("payload") or {}).get("refund") or {}).get("entity")
		if not entity:
			return None
		return {"id": entity.get("id"), "status": _REFUND_STATUS.get(entity.get("status"), "Failed")}

	def verify_webhook_signature(self, payload: bytes, headers: dict) -> bool:
		"""HMAC-verify the raw webhook body. No DB writes; first security gate."""
		secret = self.get_credential("webhook_secret")
		signature = header_value(headers, "X-Razorpay-Signature")
		if not secret or not signature:
			return False  # the SDK would accept a signature made with an empty secret
		body = payload.decode() if isinstance(payload, bytes) else payload
		try:
			self._client().utility.verify_webhook_signature(body, signature, secret)
			return True
		except razorpay.errors.SignatureVerificationError:
			return False

	def parse_webhook_event(self, payload: dict, headers: dict | None = None) -> NormalisedEvent:
		"""The dedupe id is built from the signed body. Razorpay's X-Razorpay-Event-Id
		header is outside the signature, so a replayed body could carry a new one."""
		entities = payload.get("payload") or {}
		entity_ids = ":".join(
			f"{kind}={(entities[kind].get('entity') or {}).get('id')}" for kind in sorted(entities)
		)
		return NormalisedEvent(
			gateway_event_id=f"{payload.get('event')}:{payload.get('created_at')}:{entity_ids}"[:140],
			event_type=payload.get("event"),
			payload=payload,
		)

	def get_transaction_status(self, gateway_txn_id: str) -> str:
		return self._client().payment.fetch(gateway_txn_id).get("status")

	def get_payment(self, payment_id: str) -> dict:
		"""The authoritative captured amount and currency (paise). The checkout-callback signature does
		not bind the amount, so any crediting path must read it from here, never from the request."""
		return self._client().payment.fetch(payment_id)

	def verify_payment(self, payment_id: str) -> VerifiedPayment:
		try:
			return _verified(self._client().payment.fetch(payment_id))
		except _TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e

	def find_order_payment(self, order_id: str) -> VerifiedPayment | None:
		"""An in-app order is an order (`order_`); a hosted one is a Payment Link (`plink_`)."""
		if order_id.startswith("plink_"):
			return self.checkout_payment(order_id)
		try:
			payments = _order_payments(self._client(), order_id)
		except _TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e
		captured = next((p for p in payments if p.get("status") == "captured"), None)
		return _verified(captured) if captured else None

	def checkout_payment(self, session_id: str) -> VerifiedPayment | None:
		link = self.get_checkout_session(session_id)
		if link.get("status") != "paid":
			return None
		captured = next((p for p in link.get("payments") or [] if p.get("status") == "captured"), None)
		if not captured:
			return None
		return VerifiedPayment(
			payment_id=captured.get("payment_id"),
			captured=True,
			amount=frappe.utils.flt(link.get("amount_paid")) / 100,
			currency=(link.get("currency") or "").upper(),
			order_id=session_id,
		)

	@staticmethod
	def payment_from_event(payload: dict) -> VerifiedPayment | None:
		"""The payment entity of a signed event. Its `notes` are never read: the payer can set them."""
		entity = ((payload.get("payload") or {}).get("payment") or {}).get("entity")
		return _verified(entity) if entity and entity.get("id") else None

	def create_order(
		self, amount, currency: str, receipt: str, notes: dict | None = None, customer: str | None = None
	) -> dict:
		"""A one-time Razorpay order for a wallet top-up; the UI opens Checkout against it."""
		order = self._client().order.create(
			{
				"amount": round((amount or 0) * 100),
				"currency": (currency or "INR").upper(),
				"receipt": receipt,
				"payment_capture": 1,  # auto-capture so the top-up settles + the webhook fires
				"notes": notes or {},
			}
		)
		# Checkout reads paise from `amount_in_subunits`, which leaves the rupee `amount` of
		# the caller untouched. `customer_id` lets Checkout prefill the reused customer.
		return {
			"order_id": order.get("id"),
			"key_id": self.get_credential("api_key"),
			"amount_in_subunits": order.get("amount"),
			"currency": (currency or "INR").upper(),
			"customer_id": customer,
		}

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
		"""A hosted Payment Link. Razorpay returns the payer to `success_url` and fires the
		payment webhook; `cancel_url` is unused, as a link has one callback."""
		link = self._client().payment_link.create(
			{
				"amount": round((amount or 0) * 100),
				"currency": (currency or "INR").upper(),
				"accept_partial": False,
				"description": (notes or {}).get("purpose") or "Payment",
				"reference_id": receipt,
				"callback_url": success_url,
				"callback_method": "get",
				"notes": notes or {},
			}
		)
		return {
			"checkout_url": link.get("short_url"),
			"session_id": link.get("id"),
			"key_id": self.get_credential("api_key"),
		}

	def get_checkout_session(self, session_id: str) -> dict:
		"""Fetch the Payment Link to confirm it was paid (status == 'paid')."""
		return self._client().payment_link.fetch(session_id)

	def create_customer(self, team) -> str:
		# owner_user is the email. fail_existing="0" returns a customer Razorpay already
		# has for it instead of an error; it must be the string "0", as int 0 means fail.
		customer = self._client().customer.create(
			{
				"name": getattr(team, "name", None),
				"email": team.get("owner_user") if hasattr(team, "get") else None,
				"contact": team.get("phone") if hasattr(team, "get") else None,
				"fail_existing": "0",
			}
		)
		return customer.get("id")

	def update_customer(self, customer_id: str, info: dict) -> None:
		"""Set the non-empty name, email and contact. A clash with a customer that owns the same email
		and contact is raised, because the caller recovers by switching to that customer."""
		fields = {k: info.get(k) for k in ("name", "email", "contact") if info.get(k)}
		if fields:
			self._client().customer.edit(customer_id, fields)

	def verify_payment_signature(self, data: dict) -> bool:
		"""Verify a Checkout callback (payment_id, order_id, signature), not a webhook signature."""
		try:
			self._client().utility.verify_payment_signature(data)
			return True
		except razorpay.errors.SignatureVerificationError:
			return False

	def cancel_mandate(self, mandate_reference: str, customer_reference: str | None = None) -> bool:
		"""Revoke the UPI Autopay token (mandate_reference = token id)."""
		self._client().token.cancel(customer_reference, mandate_reference)
		return True

	def get_mandate_status(self, mandate_reference: str) -> str:
		return self._client().invoice.fetch(mandate_reference).get("status")


# A pending refund can still fail, so it is not Completed.
_REFUND_STATUS = {"processed": "Completed", "pending": "Pending", "failed": "Failed"}


def _verified(payment: dict) -> VerifiedPayment:
	"""A Razorpay payment entity, read back as what the gateway says was paid."""
	return VerifiedPayment(
		payment_id=payment.get("id"),
		captured=payment.get("status") == "captured",
		amount=frappe.utils.flt(payment.get("amount")) / 100,
		currency=(payment.get("currency") or "").upper(),
		order_id=payment.get("order_id"),
	)


def _order_payments(client, order_id: str) -> list[dict]:
	return (client.order.payments(order_id) or {}).get("items") or []


def _settled_or_live(payments: list[dict]) -> PaymentResult | None:
	"""The answer an order's earlier payments already give, or None to charge."""
	for payment in payments:
		if payment.get("status") == "captured":
			return PaymentResult(
				success=True, status="Captured", gateway_transaction_id=payment.get("id"), raw=dict(payment)
			)
	if any(p.get("status") in ("created", "authorized") for p in payments):
		raise GatewayTimeout("An earlier payment on this order is still in progress.")
	return None


def _refund_key(key: str) -> str:
	"""Razorpay takes 10 to 40 characters of letters, digits, `_` and `-`, and the key must
	not repeat across the sites that share one Razorpay account: a SHA-1 of both is 40."""
	return hashlib.sha1(f"{frappe.local.site}:{key}".encode()).hexdigest()


def _recurring_charge(invoice, payment_method, order_id: str, payer: dict) -> dict:
	"""The createRecurring body. Razorpay refuses a recurring payment without the
	payer's email and contact, even when the customer already holds them."""
	return {
		"amount": round((invoice.amount or 0) * 100),
		"currency": (invoice.currency or "").upper(),
		"order_id": order_id,
		"customer_id": invoice.get("customer_id"),
		"token": payment_method.gateway_method_id,
		"recurring": "1",
		"email": payer.email,
		"contact": payer.phone,
	}


def _recurring_result(payment: dict) -> PaymentResult:
	"""What a recurring payment's own status means for the attempt. A UPI or e-mandate debit is
	asynchronous, so until the bank moves the money the attempt is held, not failed: nothing
	charges again and the `payment.captured` webhook settles it."""
	status = payment.get("status")
	known = {"gateway_transaction_id": payment.get("id"), "raw": dict(payment)}
	if status == "captured":
		return PaymentResult(success=True, status="Captured", **known)
	if status == "failed":
		return PaymentResult(
			success=False,
			status="Failed",
			failure_code=payment.get("error_code"),
			decline_code=payment.get("error_reason"),
			failure_reason=payment.get("error_description"),
			**known,
		)
	hold = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=RECURRING_HOLD_HOURS)
	return PaymentResult(success=False, status=status, hold_until=str(hold), **known)


def _refused(reason: str) -> PaymentResult:
	"""A recurring debit Razorpay would not create. Nothing was taken."""
	return PaymentResult(
		success=False,
		status="Failed",
		failure_code=REQUEST_REFUSED,
		failure_reason=reason,
		raw={"description": reason},
	)
