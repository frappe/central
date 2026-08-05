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


def make_paypal_gateway(name="GW-Test-PayPal"):
	if frappe.db.exists("Payment Gateway", name):
		frappe.delete_doc("Payment Gateway", name, force=True)
	return frappe.get_doc(
		{
			"doctype": "Payment Gateway",
			"__newname": name,
			"title": "PayPal (Test)",
			"adapter_key": "Paypal",
			"currency": "USD",
			"api_key": "pp_client",
			"api_secret": "pp_secret",
			"webhook_secret": "WH-ID-1",
			"is_enabled": 1,
		}
	).insert(ignore_permissions=True)


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
