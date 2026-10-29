# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
import requests

from central.billing.gateways.paypal_adapter import PayPalAdapter
from central.billing.gateways.registry import get_adapter
from central.billing.tests.gateway_contract import GatewayAdapterContract
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase


def make_paypal_gateway(currencies=(("USD", 0),), **values):
	"""The PayPal gateway, configured for test. There is only one (named "Paypal")."""
	from central.billing.tests.utils import configure_gateway

	return configure_gateway(
		"Paypal",
		currencies,
		api_key="pp_client",
		api_secret="pp_secret",
		webhook_secret="WH-ID-1",
		is_enabled=1,
		**values,
	)


class TestPayPalAdapter(GatewayAdapterContract, IntegrationTestCase):
	def make_adapter(self):
		return PayPalAdapter(make_paypal_gateway())

	def webhook_headers(self):
		return {
			"PAYPAL-TRANSMISSION-ID": "t",
			"PAYPAL-TRANSMISSION-SIG": "s",
			"PAYPAL-TRANSMISSION-TIME": "now",
			"PAYPAL-AUTH-ALGO": "SHA256",
			"PAYPAL-CERT-URL": "url",
		}

	@contextmanager
	def signature_valid(self):
		with patch.object(PayPalAdapter, "_verify_webhook", return_value=True):
			yield

	@contextmanager
	def signature_invalid(self):
		with patch.object(PayPalAdapter, "_verify_webhook", return_value=False):
			yield

	def make_charge_inputs(self):
		invoice = frappe._dict(amount=40.0, currency="USD", name="INV-1")
		method = frappe._dict(gateway_method_id="vault_x")
		return invoice, method, "PA-PP-001"

	@contextmanager
	def charge_succeeds(self, txn_id="txn_ok"):
		with patch.object(
			PayPalAdapter, "_capture_payment", return_value={"id": txn_id, "status": "COMPLETED"}
		) as m:
			self._cap = m
			yield

	@contextmanager
	def charge_declines(self, code="card_declined"):
		with patch.object(
			PayPalAdapter,
			"_capture_payment",
			return_value={
				"id": None,
				"status": "DECLINED",
				"failure_code": code,
				"failure_reason": "declined",
			},
		) as m:
			self._cap = m
			yield

	@contextmanager
	def charge_times_out(self):
		with patch.object(
			PayPalAdapter, "_capture_payment", side_effect=requests.exceptions.ConnectionError("timeout")
		) as m:
			self._cap = m
			yield

	def captured_idempotency_key(self):
		return self._cap.call_args.kwargs["request_id"]

	def make_refund_inputs(self):
		attempt = frappe._dict(gateway_transaction_id="cap_charged", currency="USD", name="PA-1")
		return attempt, 40.0, "duplicate charge"

	@contextmanager
	def refund_succeeds(self, refund_id="rfnd_ok"):
		with patch.object(
			PayPalAdapter, "_refund_capture", return_value={"id": refund_id, "status": "COMPLETED"}
		):
			yield

	def parse_event_inputs(self):
		payload = {"id": "WH-evt-1", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {"id": "cap_x"}}
		return payload, self.webhook_headers(), "WH-evt-1", "PAYMENT.CAPTURE.COMPLETED"

	def setup_inputs(self):
		return "Team-1", {"customer_id": "cust_x"}

	@contextmanager
	def stub_setup(self):
		with patch.object(
			PayPalAdapter,
			"_create_setup_token",
			return_value={"id": "setup_1", "links": [{"rel": "approve", "href": "https://approve"}]},
		):
			yield

	def validation_inputs(self):
		return frappe._dict(gateway_method_id="vault_x")

	@contextmanager
	def stub_validation_success(self):
		# A live vault token is the proof — no gateway round-trip.
		yield

	def expected_account_currency(self):
		# PayPal's OAuth response carries no settlement currency.
		return None

	@contextmanager
	def stub_credentials_valid(self):
		with patch.object(PayPalAdapter, "_token", return_value="tok"):
			yield

	@contextmanager
	def stub_credentials_invalid(self):
		err = requests.exceptions.HTTPError("401 Unauthorized")
		err.response = MagicMock(status_code=401)
		with patch.object(PayPalAdapter, "_token", side_effect=err):
			yield

	# --- PayPal-specific -----------------------------------------------------

	def test_register_webhook_returns_webhook_id_as_secret(self):
		adapter = self.make_adapter()
		with patch.object(PayPalAdapter, "_create_webhook", return_value={"id": "WH-NEW-1"}):
			result = adapter.register_webhook(
				"https://site/api/method/central.billing.payments.webhooks.paypal"
			)
		# PayPal verifies by webhook id, so it doubles as the stored "secret".
		self.assertEqual(result["endpoint_id"], "WH-NEW-1")
		self.assertEqual(result["secret"], "WH-NEW-1")

	def test_registry_resolves_paypal(self):
		adapter = get_adapter(make_paypal_gateway())
		self.assertIsInstance(adapter, PayPalAdapter)

	def test_capture_maps_4xx_decline_to_status_not_exception(self):
		adapter = self.make_adapter()
		resp = MagicMock(status_code=402)
		resp.json.return_value = {"name": "INSTRUMENT_DECLINED", "message": "declined"}
		with (
			patch.object(PayPalAdapter, "_token", return_value="tok"),
			patch("central.billing.gateways.paypal_adapter.requests.post", return_value=resp),
		):
			out = adapter._capture_payment("vault_x", 40.0, "USD", "req-1")
		self.assertEqual(out["status"], "DECLINED")
		self.assertEqual(out["failure_code"], "INSTRUMENT_DECLINED")

	def test_capture_extracts_capture_id_on_success(self):
		adapter = self.make_adapter()
		resp = MagicMock(status_code=201)
		resp.json.return_value = {
			"id": "order_1",
			"purchase_units": [
				{
					"payments": {
						"captures": [
							{
								"id": "cap_9",
								"status": "COMPLETED",
								"amount": {"value": "40.00", "currency_code": "USD"},
							}
						]
					}
				}
			],
		}
		with (
			patch.object(PayPalAdapter, "_token", return_value="tok"),
			patch("central.billing.gateways.paypal_adapter.requests.post", return_value=resp),
		):
			out = adapter._capture_payment("vault_x", 40.0, "USD", "req-2")
		self.assertEqual(out, {"id": "cap_9", "status": "COMPLETED", "amount": "40.00", "currency": "USD"})

	def test_a_pending_capture_stays_open(self):
		"""PayPal may still take the money, so a PENDING capture is not a decline."""
		adapter = self.make_adapter()
		invoice, method, key = self.make_charge_inputs()
		with patch.object(
			PayPalAdapter, "_capture_payment", return_value={"id": "cap_p", "status": "PENDING"}
		):
			result = adapter.charge(invoice, method, key)
		self.assertEqual(
			(result.success, result.status, result.gateway_transaction_id), (False, "Pending", "cap_p")
		)
		self.assertTrue(result.hold_until)

	def test_a_duplicate_request_is_unknown_not_a_decline(self):
		from central.billing.gateways.base import GatewayTimeout

		adapter = self.make_adapter()
		resp = MagicMock(status_code=422)
		resp.json.return_value = {"name": "DUPLICATE_REQUEST_ID", "message": "in progress"}
		with (
			patch.object(PayPalAdapter, "_token", return_value="tok"),
			patch("central.billing.gateways.paypal_adapter.requests.post", return_value=resp),
		):
			with self.assertRaises(GatewayTimeout):
				adapter._capture_payment("vault_x", 40.0, "USD", "req-dup")

	def test_the_oauth_token_is_reused(self):
		adapter = self.make_adapter()
		frappe.cache.delete_value(f"paypal_token::{adapter.gateway.name}")
		resp = MagicMock(status_code=200)
		resp.json.return_value = {"access_token": "tok_1", "expires_in": 32400}
		with patch("central.billing.gateways.paypal_adapter.requests.post", return_value=resp) as post:
			self.assertEqual((adapter._token(), adapter._token()), ("tok_1", "tok_1"))
		post.assert_called_once()

	def test_only_paypal_hosts_receive_the_secret(self):
		from central.billing.gateways.base import GatewayError

		with patch.dict(frappe.local.conf, {"paypal_api_base": "https://attacker.example"}):
			with self.assertRaises(GatewayError):
				self.make_adapter()._base()
		with patch.dict(frappe.local.conf, {"paypal_api_base": "https://api-m.paypal.com"}):
			self.assertEqual(self.make_adapter()._base(), "https://api-m.paypal.com")

	def test_a_capture_event_binds_by_order_not_custom_id(self):
		payload = {
			"event_type": "PAYMENT.CAPTURE.COMPLETED",
			"resource": {
				"id": "cap_1",
				"status": "COMPLETED",
				"custom_id": "set-by-the-browser",
				"amount": {"value": "25.00", "currency_code": "USD"},
				"supplementary_data": {"related_ids": {"order_id": "ORDER-1"}},
			},
		}
		payment = PayPalAdapter.payment_from_event(payload)
		self.assertEqual((payment.order_id, payment.receipt, payment.amount), ("ORDER-1", None, 25.0))

	def test_a_resolved_dispute_in_the_buyers_favour_is_lost(self):
		payload = {
			"event_type": "CUSTOMER.DISPUTE.RESOLVED",
			"resource": {
				"dispute_id": "PP-D-1",
				"disputed_transactions": [{"seller_transaction_id": "cap_1"}],
				"dispute_amount": {"value": "25.00"},
				"dispute_outcome": {"outcome_code": "RESOLVED_BUYER_FAVOUR"},
			},
		}
		dispute = PayPalAdapter.dispute_from_event(payload)
		self.assertEqual(
			(dispute["payment_id"], dispute["status"], dispute["amount"]), ("cap_1", "lost", 25.0)
		)

	def test_a_dispute_the_merchant_accepted_is_lost(self):
		payload = {
			"event_type": "CUSTOMER.DISPUTE.RESOLVED",
			"resource": {
				"dispute_id": "PP-D-2",
				"disputed_transactions": [{"seller_transaction_id": "cap_2"}],
				"dispute_amount": {"value": "25.00"},
				"dispute_outcome": {"outcome_code": "ACCEPTED"},
			},
		}
		self.assertEqual(PayPalAdapter.dispute_from_event(payload)["status"], "lost")

	def test_a_saved_paypal_account_is_read_from_the_vault(self):
		adapter = self.make_adapter()
		token = {"id": "vault_tok", "payment_source": {"paypal": {"email_address": "buyer@example.com"}}}
		with patch.object(PayPalAdapter, "_create_payment_token", return_value=token) as create:
			card = adapter.read_saved_card("setup_1")
		create.assert_called_once_with("setup_1")
		self.assertEqual((card["payment_method"], card["label"]), ("vault_tok", "buyer@example.com"))

	def test_an_order_is_paid_only_once_captured(self):
		adapter = self.make_adapter()
		captured = {
			"id": "order_7",
			"status": "COMPLETED",
			"purchase_units": [
				{
					"payments": {
						"captures": [
							{
								"id": "cap_7",
								"status": "COMPLETED",
								"amount": {"value": "40.00", "currency_code": "usd"},
							}
						]
					}
				}
			],
		}
		with patch.object(PayPalAdapter, "_get_order", return_value={"id": "order_7", "status": "APPROVED"}):
			self.assertIsNone(adapter.find_order_payment("order_7"))
		with patch.object(PayPalAdapter, "_get_order", return_value=captured):
			payment = adapter.find_order_payment("order_7")
		self.assertEqual(
			(payment.payment_id, payment.amount, payment.currency, payment.order_id),
			("cap_7", 40.0, "USD", "order_7"),
		)
