# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Razorpay GatewayAdapter.

One of two modules allowed to import a gateway SDK. Gateway knowledge (recurring
charge against a mandate token, refund, webhook signature + event shapes) is
ported from the working press implementation; the structure is the new adapter
model. The UPI Autopay mandate *lifecycle* (cap = trust tier) is issue #08.
"""

import frappe
import razorpay
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

# Razorpay raises these for transient/server failures; declines are BadRequestError.
_TRANSIENT = (
	razorpay.errors.GatewayError,
	razorpay.errors.ServerError,
	requests.exceptions.RequestException,
)

# The charge lifecycle events the webhook spine consumes (see webhooks.py).
RAZORPAY_WEBHOOK_EVENTS = [
	"payment.captured",
	"payment.failed",
	"payment.authorized",
	"refund.processed",
]


class RazorpayAdapter(GatewayAdapter):
	# common_site_config.json overrides for live keys (see GatewayAdapter.get_credential).
	conf_keys = {
		"api_key": "razorpay_key_id",
		"api_secret": "razorpay_key_secret",
		"webhook_secret": "razorpay_webhook_secret",
	}

	# RBI caps a silent (off-session) recurring debit at ₹15,000; above it the
	# customer must re-authenticate every cycle, so we don't auto-charge there
	# (ADR 0005). Each debit is preceded by a pre-debit notification.
	supports_off_session_charge = True
	max_silent_charge = 15_00_000  # ₹15,000 in paise
	requires_predebit_notice = True

	def _client(self):
		return razorpay.Client(
			auth=(self.get_credential("api_key"), self.get_credential("api_secret"))
		)

	def validate_credentials(self) -> dict:
		"""Cheapest authed read — list one payment to prove key/secret work.

		Razorpay maps 401/4xx to BadRequestError → bad keys; transient/server
		failures raise GatewayTimeout. Razorpay settles in INR."""
		try:
			self._client().payment.all({"count": 1})
		except razorpay.errors.BadRequestError as e:
			raise GatewayAuthError(str(e)) from e
		except _TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e
		return {"account_id": self.get_credential("api_key"), "currency": "INR"}

	def register_webhook(self, callback_url: str, events: list[str] | None = None) -> dict:
		"""Create a Razorpay webhook. Razorpay takes a caller-chosen secret, so we
		generate a strong one server-side, register it, and return it to store."""
		secret = frappe.generate_hash(length=32)
		# Razorpay wants events as an object {name: 1}, not a list — a list is
		# serialised positionally and the API rejects it ("Invalid event name/names: 1, 2, 3").
		webhook = self._client().webhook.create({
			"url": callback_url,
			"secret": secret,
			"events": {name: 1 for name in (events or RAZORPAY_WEBHOOK_EVENTS)},
		})
		return {"endpoint_id": webhook.get("id"), "secret": secret}

	def setup_payment_method(self, team, setup_data: dict) -> dict:
		"""Create a recurring authorisation order — UPI Autopay or card.

		`method` selects the rail ("upi" default, or "card"); `max_amount` becomes
		the token's ceiling. The UI runs Razorpay Checkout against the returned
		order to capture the recurring token. The recurring `charge()` path is the
		same for both rails (it charges the token).
		"""
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

	def validate_payment_method(self, payment_method) -> bool:
		"""Razorpay validation is the mandate authorisation itself (token.confirmed);
		a live token is the proof. No separate micro-charge."""
		return bool(payment_method.gateway_method_id)

	def charge(self, invoice, payment_method, idempotency_key: str) -> PaymentResult:
		"""Off-session recurring charge against a mandate token.

		An order carries the idempotency key as its (unique) receipt; the
		recurring payment is created against the token. Declines come back as a
		failed result; transient/network errors raise GatewayTimeout so a retry
		reuses the same receipt.
		"""
		client = self._client()
		amount_paise = int(round((invoice.amount or 0) * 100))
		currency = (invoice.currency or "").upper()
		try:
			order = client.order.create(
				{
					"amount": amount_paise,
					"currency": currency,
					"receipt": idempotency_key,
					"payment_capture": 1,  # settle the charge, don't leave it authorized
					"notes": {"invoice": invoice.get("name")},
				}
			)
			payment = client.payment.createRecurring(
				{
					"amount": amount_paise,
					"currency": currency,
					"order_id": order["id"],
					"customer_id": invoice.get("customer_id"),
					"token": payment_method.gateway_method_id,
					"recurring": "1",
				}
			)
		except razorpay.errors.BadRequestError as e:
			return PaymentResult(
				success=False,
				status="Failed",
				failure_code=getattr(e, "code", None),
				failure_reason=str(e),
			)
		except _TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e

		captured = payment.get("status") == "captured"
		return PaymentResult(
			success=captured,
			status="Captured" if captured else payment.get("status"),
			gateway_transaction_id=payment.get("id"),
			raw=dict(payment),
		)

	def refund(self, payment_attempt, amount, reason: str) -> RefundResult:
		client = self._client()
		try:
			refund = client.payment.refund(
				payment_attempt.gateway_transaction_id,
				{"amount": int(round((amount or 0) * 100))},
			)
		except _TRANSIENT as e:
			raise GatewayTimeout(str(e)) from e

		done = refund.get("status") in ("processed", "pending")
		return RefundResult(
			success=done,
			status="Completed" if done else refund.get("status"),
			gateway_refund_id=refund.get("id"),
			raw=dict(refund),
		)

	def verify_webhook_signature(self, payload: bytes, headers: dict) -> bool:
		"""HMAC-verify the raw webhook body. No DB writes; first security gate."""
		secret = self.get_credential("webhook_secret")
		signature = header_value(headers, "X-Razorpay-Signature")
		body = payload.decode() if isinstance(payload, bytes) else payload
		try:
			self._client().utility.verify_webhook_signature(body, signature, secret)
			return True
		except razorpay.errors.SignatureVerificationError:
			return False

	def parse_webhook_event(self, payload: dict, headers: dict | None = None) -> NormalisedEvent:
		"""Razorpay carries the dedupe id in the X-Razorpay-Event-Id header."""
		return NormalisedEvent(
			gateway_event_id=header_value(headers, "X-Razorpay-Event-Id"),
			event_type=payload.get("event"),
			payload=payload,
		)

	def get_transaction_status(self, gateway_txn_id: str) -> str:
		return self._client().payment.fetch(gateway_txn_id).get("status")

	def create_order(self, amount, currency: str, receipt: str, notes: dict | None = None,
					 customer: str | None = None) -> dict:
		"""A one-time Razorpay order for a wallet top-up; the UI opens Checkout against it."""
		order = self._client().order.create({
			"amount": int(round((amount or 0) * 100)),
			"currency": (currency or "INR").upper(),
			"receipt": receipt,
			"payment_capture": 1,  # auto-capture so the top-up settles + the webhook fires
			"notes": notes or {},
		})
		# `amount_in_subunits` (paise) is what Razorpay Checkout reads; it is kept
		# distinct from the human-currency `amount` create_topup_order returns, so
		# the spread of these handles never clobbers the rupee amount confirm_topup
		# credits the wallet with. `customer_id` rides along (an order takes no customer
		# server-side) so Checkout prefills the same customer reused for recurring charges.
		return {"order_id": order.get("id"), "key_id": self.get_credential("api_key"),
				"amount_in_subunits": order.get("amount"), "currency": (currency or "INR").upper(),
				"customer_id": customer}

	def create_customer(self, team) -> str:
		# Team.owner_user is a Link to User, whose name IS the email address.
		# Primary idempotency is ours — ensure_gateway_customer stores the id per
		# (team, gateway) before the order runs. fail_existing="0" is a backstop (as
		# in press): if a customer with this email already exists at Razorpay (a
		# pre-store orphan), return it instead of erroring "Customer already exists".
		# Must be the STRING "0"; int 0 is treated as the default (1 = fail).
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
		"""Sync name/email/contact onto an existing customer. Razorpay requires a
		contact on the customer before a recurring order, and a customer minted
		earlier (or by an older flow) may not have one — so we set it here, idempotently.
		Only non-empty values are sent."""
		fields = {k: info.get(k) for k in ("name", "email", "contact") if info.get(k)}
		if fields:
			self._client().customer.edit(customer_id, fields)

	def verify_payment_signature(self, data: dict) -> bool:
		"""Verify a Razorpay Checkout callback (payment_id + order_id + signature).

		Distinct from the webhook signature; used when the client completes UPI
		Autopay authorisation or a one-time order.
		"""
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
