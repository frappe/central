# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
import razorpay
import requests

from central.billing.gateways.razorpay_adapter import RazorpayAdapter
from central.billing.tests.gateway_contract import GatewayAdapterContract
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import complete_billing_profile, ensure_team


def make_razorpay_gateway(currencies=(("INR", 1),)):
	"""The Razorpay gateway, configured for test. There is only one (named "Razorpay")."""
	from central.billing.tests.utils import configure_gateway

	return configure_gateway(
		"Razorpay",
		currencies,
		api_key="rzp_test_key",
		api_secret="rzp_test_secret",
		webhook_secret="rzp_whsec",
		is_enabled=1,
		supports_mandates=1,
	)


class TestRazorpayAdapter(GatewayAdapterContract, IntegrationTestCase):
	def make_adapter(self):
		return RazorpayAdapter(make_razorpay_gateway())

	@contextmanager
	def _client(self):
		client = MagicMock()
		with patch("central.billing.gateways.razorpay_adapter.razorpay.Client", return_value=client):
			self._mock = client
			yield client

	def webhook_headers(self):
		return {"X-Razorpay-Signature": "sig"}

	@contextmanager
	def signature_valid(self):
		with self._client() as c:
			c.utility.verify_webhook_signature.return_value = True
			yield

	@contextmanager
	def signature_invalid(self):
		with self._client() as c:
			c.utility.verify_webhook_signature.side_effect = razorpay.errors.SignatureVerificationError(
				"bad sig"
			)
			yield

	def make_charge_inputs(self):
		# The order prepare_charge created and Central stored before charging.
		invoice = frappe._dict(
			amount=40.0, currency="INR", customer_id="cust_x", name="INV-1", order_id="order_x"
		)
		team = complete_billing_profile(ensure_team("rzp-adapter-team"))
		method = frappe._dict(gateway_method_id="token_x", team=team)
		return invoice, method, "PA-R-001"

	@contextmanager
	def _recurring_payment(self, **payment):
		"""createRecurring answers with ids only; the payment entity carries the outcome."""
		with self._client() as c:
			c.order.payments.return_value = {"items": []}
			c.payment.createRecurring.return_value = {"razorpay_payment_id": payment["id"]}
			c.payment.fetch.return_value = payment
			yield c

	@contextmanager
	def charge_succeeds(self, txn_id="txn_ok"):
		with self._recurring_payment(id=txn_id, status="captured"):
			yield

	@contextmanager
	def charge_declines(self, code="card_declined"):
		with self._recurring_payment(id="pay_failed", status="failed", error_code=code):
			yield

	def test_a_recurring_debit_sends_the_payers_email_and_contact(self):
		adapter = self.make_adapter()
		invoice, method, key = self.make_charge_inputs()
		with self.charge_succeeds():
			adapter.charge(invoice, method, key)
		body = self._mock.payment.createRecurring.call_args.args[0]
		self.assertEqual((body["email"], body["contact"]), ("billing@test.example", "9999999999"))

	def test_a_debit_still_in_progress_is_held_not_failed(self):
		adapter = self.make_adapter()
		invoice, method, key = self.make_charge_inputs()
		with self._recurring_payment(id="pay_async", status="created"):
			result = adapter.charge(invoice, method, key)
		self.assertFalse(result.success)
		self.assertEqual(result.gateway_transaction_id, "pay_async")
		self.assertTrue(result.hold_until)

	def test_a_refused_request_is_not_a_decline(self):
		from central.billing.payments import decline

		adapter = self.make_adapter()
		invoice, method, key = self.make_charge_inputs()
		with self._client() as c:
			c.order.payments.return_value = {"items": []}
			c.payment.createRecurring.side_effect = razorpay.errors.BadRequestError(
				"The contact field is required."
			)
			result = adapter.charge(invoice, method, key)
		self.assertEqual(result.failure_code, decline.REQUEST_REFUSED)
		self.assertFalse(decline.is_retryable_later(result.failure_code, None))

	def test_a_payer_without_a_phone_is_refused_before_the_gateway(self):
		from central.billing.payments import decline

		adapter = self.make_adapter()
		invoice, method, key = self.make_charge_inputs()
		frappe.db.set_value("Billing Profile", method.team, "phone", None)
		with self._client() as c:
			c.order.payments.return_value = {"items": []}
			result = adapter.charge(invoice, method, key)
		self.assertEqual(result.failure_code, decline.REQUEST_REFUSED)
		c.payment.createRecurring.assert_not_called()

	def test_a_resumed_charge_returns_its_payment_even_without_a_phone(self):
		adapter = self.make_adapter()
		invoice, method, key = self.make_charge_inputs()
		frappe.db.set_value("Billing Profile", method.team, "phone", None)
		with self._client() as c:
			c.order.payments.return_value = {"items": [{"id": "pay_first", "status": "captured"}]}
			result = adapter.charge(invoice, method, key)
		self.assertTrue(result.success)
		self.assertEqual(result.gateway_transaction_id, "pay_first")

	@contextmanager
	def charge_times_out(self):
		with self._client() as c:
			c.order.payments.side_effect = requests.exceptions.ConnectionError("connection timed out")
			yield

	def test_timeout_raises_gateway_timeout_and_forwards_idempotency_key(self):
		"""Razorpay has no charge idempotency key. Retry safety is the stored order: every
		charge reads that order's payments before it makes one."""
		from central.billing.gateways.base import GatewayTimeout

		adapter = self.make_adapter()
		invoice, method, key = self.make_charge_inputs()
		with self.charge_times_out():
			with self.assertRaises(GatewayTimeout):
				adapter.charge(invoice, method, key)
		self._mock.order.payments.assert_called_once_with("order_x")
		self._mock.payment.createRecurring.assert_not_called()

	def test_a_retry_returns_the_payment_the_order_already_has(self):
		adapter = self.make_adapter()
		invoice, method, key = self.make_charge_inputs()
		with self._client() as c:
			c.order.payments.return_value = {"items": [{"id": "pay_first", "status": "captured"}]}
			result = adapter.charge(invoice, method, key)
		self.assertEqual(result.gateway_transaction_id, "pay_first")
		c.payment.createRecurring.assert_not_called()

	def test_a_retry_waits_for_a_payment_still_in_progress(self):
		from central.billing.gateways.base import GatewayTimeout

		adapter = self.make_adapter()
		invoice, method, key = self.make_charge_inputs()
		with self._client() as c:
			c.order.payments.return_value = {"items": [{"id": "pay_first", "status": "created"}]}
			with self.assertRaises(GatewayTimeout):
				adapter.charge(invoice, method, key)
		c.payment.createRecurring.assert_not_called()

	def test_prepare_charge_sends_a_receipt_razorpay_accepts(self):
		adapter = self.make_adapter()
		invoice, _method, _key = self.make_charge_inputs()
		with self._client() as c:
			c.order.create.return_value = {"id": "order_new"}
			self.assertEqual(adapter.prepare_charge(invoice, "x" * 64), "order_new")
		self.assertLessEqual(len(c.order.create.call_args.args[0]["receipt"]), 40)

	def test_a_refund_is_sent_with_an_idempotency_header(self):
		adapter = self.make_adapter()
		payment_attempt, amount, reason = self.make_refund_inputs()
		with self.refund_succeeds():
			adapter.refund(payment_attempt, amount, reason, "REF-0001")
		header = self._mock.payment.refund.call_args.kwargs["headers"]["X-Refund-Idempotency"]
		self.assertEqual(len(header), 40)

	def test_the_sdk_sends_the_refund_idempotency_header(self):
		"""Drives the real SDK client, so a change to its refund signature fails here."""
		adapter = self.make_adapter()
		payment_attempt, amount, reason = self.make_refund_inputs()
		client = razorpay.Client(auth=("rzp_test_key", "rzp_test_secret"))
		response = MagicMock(status_code=200)
		response.json.return_value = {"id": "rfnd_sdk", "status": "processed"}
		with (
			patch.object(RazorpayAdapter, "_client", return_value=client),
			patch.object(client.session, "post", return_value=response) as post,
		):
			result = adapter.refund(payment_attempt, amount, reason, "REF-0002")

		self.assertEqual(result.gateway_refund_id, "rfnd_sdk")
		self.assertEqual(len(post.call_args.kwargs["headers"]["X-Refund-Idempotency"]), 40)

	def make_refund_inputs(self):
		payment_attempt = frappe._dict(gateway_transaction_id="pay_charged")
		return payment_attempt, 40.0, "duplicate charge"

	@contextmanager
	def refund_succeeds(self, refund_id="rfnd_ok"):
		with self._client() as c:
			c.payment.refund.return_value = {"id": refund_id, "status": "processed"}
			yield

	def parse_event_inputs(self):
		payload = {
			"event": "payment.captured",
			"created_at": 1700000000,
			"payload": {"payment": {"entity": {"id": "pay_x", "order_id": "order_x"}}},
		}
		# The header id is outside the signature, so the dedupe id comes from the body.
		headers = {"X-Razorpay-Event-Id": "evt_r1"}
		return payload, headers, "payment.captured:1700000000:payment=pay_x", "payment.captured"

	def setup_inputs(self):
		return "Team-1", {"customer_id": "cust_x", "max_amount": 5000}

	@contextmanager
	def stub_setup(self):
		with self._client() as c:
			c.order.create.return_value = {"id": "order_mandate", "amount": 100}
			yield

	def validation_inputs(self):
		return frappe._dict(gateway_method_id="token_x")

	@contextmanager
	def stub_validation_success(self):
		# Razorpay validation is the mandate authorisation itself (no micro-charge).
		with self._client():
			yield

	def expected_account_currency(self):
		return "INR"

	@contextmanager
	def stub_credentials_valid(self):
		with self._client() as c:
			c.payment.all.return_value = {"count": 0, "items": []}
			yield

	@contextmanager
	def stub_credentials_invalid(self):
		with self._client() as c:
			c.payment.all.side_effect = razorpay.errors.BadRequestError("Authentication failed")
			yield

	# --- optional, gateway-specific capabilities ----------------------------

	def test_register_webhook_generates_and_returns_secret(self):
		adapter = self.make_adapter()
		with self._client() as c:
			c.webhook.create.return_value = {"id": "wh_123"}
			result = adapter.register_webhook(
				"https://site/api/method/central.billing.payments.webhooks.razorpay"
			)
		self.assertEqual(result["endpoint_id"], "wh_123")
		# Razorpay takes a caller-chosen secret: we generate one and register it.
		self.assertTrue(result["secret"])
		sent = c.webhook.create.call_args.args[0]
		self.assertEqual(sent["secret"], result["secret"])
		self.assertEqual(sent["url"], "https://site/api/method/central.billing.payments.webhooks.razorpay")
		# Razorpay wants events as {name: 1}, not a list — see register_webhook.
		self.assertIsInstance(sent["events"], dict)
		self.assertTrue(all(v == 1 for v in sent["events"].values()))

	def test_get_webhook_reads_events_given_as_a_map(self):
		adapter = self.make_adapter()
		with self._client() as c:
			c.webhook.fetch.return_value = {
				"url": "https://site/x",
				"active": True,
				"events": {"payment.captured": True, "payment.failed": False},
			}
			webhook = adapter.get_webhook("wh_1")
		self.assertEqual(
			webhook, {"url": "https://site/x", "is_active": True, "events": ["payment.captured"]}
		)

	def test_a_refused_webhook_read_is_not_found(self):
		import razorpay

		from central.billing.gateways.base import WebhookNotFound

		adapter = self.make_adapter()
		with self._client() as c:
			c.webhook.fetch.side_effect = razorpay.errors.BadRequestError("The id provided does not exist")
			with self.assertRaises(WebhookNotFound):
				adapter.get_webhook("wh_old")

	def test_update_webhook_events_sends_the_url_and_event_map(self):
		adapter = self.make_adapter()
		with self._client() as c:
			adapter.update_webhook_events("wh_1", "https://site/x", ["payment.captured"])
		c.webhook.edit.assert_called_once_with(
			"wh_1", None, {"url": "https://site/x", "events": {"payment.captured": 1}}
		)

	def test_create_customer_returns_id(self):
		adapter = self.make_adapter()
		with self._client() as c:
			c.customer.create.return_value = {"id": "cust_new"}
			cid = adapter.create_customer(frappe._dict(name="Team-1", owner_user="a@b.com", phone="+91"))
		self.assertEqual(cid, "cust_new")
		payload = c.customer.create.call_args.args[0]
		self.assertEqual(payload["email"], "a@b.com")
		# fail_existing="0" is the backstop alongside the Gateway Customer store:
		# the STRING "0" makes Razorpay return a pre-existing customer instead of
		# erroring (int 0 is treated as the default 1 = fail).
		self.assertEqual(payload["fail_existing"], "0")

	def test_update_customer_edits_contact(self):
		adapter = self.make_adapter()
		with self._client() as c:
			adapter.update_customer("cust_x", {"name": "Acme", "email": "a@b.com", "contact": "9999999999"})
		cid, fields = c.customer.edit.call_args.args
		self.assertEqual(cid, "cust_x")
		self.assertEqual(fields["contact"], "9999999999")

	def test_verify_payment_signature_valid(self):
		adapter = self.make_adapter()
		data = {"razorpay_payment_id": "p", "razorpay_order_id": "o", "razorpay_signature": "s"}
		with self._client() as c:
			c.utility.verify_payment_signature.return_value = True
			self.assertTrue(adapter.verify_payment_signature(data))

	def test_verify_payment_signature_invalid(self):
		adapter = self.make_adapter()
		with self._client() as c:
			c.utility.verify_payment_signature.side_effect = razorpay.errors.SignatureVerificationError("bad")
			self.assertFalse(adapter.verify_payment_signature({}))

	def test_cancel_mandate_revokes_token(self):
		adapter = self.make_adapter()
		with self._client() as c:
			c.token.cancel.return_value = {"deleted": True}
			self.assertTrue(adapter.cancel_mandate("token_x", customer_reference="cust_x"))
			c.token.cancel.assert_called_once_with("cust_x", "token_x")

	def test_get_mandate_status(self):
		adapter = self.make_adapter()
		with self._client() as c:
			c.invoice.fetch.return_value = {"status": "authenticated"}
			self.assertEqual(adapter.get_mandate_status("order_x"), "authenticated")
