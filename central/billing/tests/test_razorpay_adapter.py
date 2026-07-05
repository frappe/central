# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
import razorpay
import requests
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

from central.billing.gateways.razorpay_adapter import RazorpayAdapter
from central.billing.tests.gateway_contract import GatewayAdapterContract


def make_razorpay_gateway(name="GW-Test-Razorpay"):
	if frappe.db.exists("Payment Gateway", name):
		frappe.delete_doc("Payment Gateway", name, force=True)
	doc = frappe.get_doc(
		{
			"doctype": "Payment Gateway",
			"__newname": name,
			"title": "Razorpay (Test)",
			"adapter_key": "Razorpay",
			"currencies": [{"currency": "INR", "is_default": 1}],
			"api_key": "rzp_test_key",
			"api_secret": "rzp_test_secret",
			"webhook_secret": "rzp_whsec",
			"is_enabled": 1,
			"supports_mandates": 1,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


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
		invoice = frappe._dict(amount=40.0, currency="INR", customer_id="cust_x", name="INV-1")
		method = frappe._dict(gateway_method_id="token_x")
		return invoice, method, "PA-R-001"

	@contextmanager
	def charge_succeeds(self, txn_id="txn_ok"):
		with self._client() as c:
			c.order.create.return_value = {"id": "order_x"}
			c.payment.createRecurring.return_value = {"id": txn_id, "status": "captured"}
			yield

	@contextmanager
	def charge_declines(self, code="card_declined"):
		with self._client() as c:
			c.order.create.return_value = {"id": "order_x"}
			err = razorpay.errors.BadRequestError("Payment was declined")
			err.code = code
			c.payment.createRecurring.side_effect = err
			yield

	@contextmanager
	def charge_times_out(self):
		with self._client() as c:
			c.order.create.side_effect = requests.exceptions.ConnectionError("connection timed out")
			yield

	def captured_idempotency_key(self):
		# Razorpay's idempotency carrier is the order receipt.
		return self._mock.order.create.call_args.args[0]["receipt"]

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
			"payload": {"payment": {"entity": {"id": "pay_x", "order_id": "order_x"}}},
		}
		headers = {"X-Razorpay-Event-Id": "evt_r1"}
		return payload, headers, "evt_r1", "payment.captured"

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
			result = adapter.register_webhook("https://site/api/method/central.billing.payments.webhooks.razorpay")
		self.assertEqual(result["endpoint_id"], "wh_123")
		# Razorpay takes a caller-chosen secret: we generate one and register it.
		self.assertTrue(result["secret"])
		sent = c.webhook.create.call_args.args[0]
		self.assertEqual(sent["secret"], result["secret"])
		self.assertEqual(sent["url"], "https://site/api/method/central.billing.payments.webhooks.razorpay")
		# Razorpay wants events as {name: 1}, not a list — see register_webhook.
		self.assertIsInstance(sent["events"], dict)
		self.assertTrue(all(v == 1 for v in sent["events"].values()))

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
			c.utility.verify_payment_signature.side_effect = razorpay.errors.SignatureVerificationError(
				"bad"
			)
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
