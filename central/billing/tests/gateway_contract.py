# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Shared GatewayAdapter contract suite.

Every adapter must satisfy these behaviours. A concrete adapter test mixes this
in alongside IntegrationTestCase and implements the SDK-stub hooks. This file
has no `test_` prefix so the runner never executes it standalone.
"""

import frappe


class GatewayAdapterContract:
	# --- hooks the concrete adapter test must provide -----------------------

	def make_adapter(self):
		raise NotImplementedError

	def signature_valid(self):
		"""Context manager: the SDK accepts the next signature check."""
		raise NotImplementedError

	def signature_invalid(self):
		"""Context manager: the SDK rejects the next signature check."""
		raise NotImplementedError

	def webhook_headers(self) -> dict:
		raise NotImplementedError

	def make_charge_inputs(self):
		"""Return (invoice, payment_method, idempotency_key) for a charge."""
		raise NotImplementedError

	def charge_succeeds(self, txn_id="txn_ok"):
		raise NotImplementedError

	def charge_declines(self, code="card_declined"):
		raise NotImplementedError

	def charge_times_out(self):
		raise NotImplementedError

	def captured_idempotency_key(self):
		"""The idempotency key the SDK was last called with."""
		raise NotImplementedError

	def make_refund_inputs(self):
		"""Return (payment_attempt, amount, reason) for a refund."""
		raise NotImplementedError

	def refund_succeeds(self, refund_id="rfnd_ok"):
		raise NotImplementedError

	def parse_event_inputs(self):
		"""Return (payload_dict, headers, expected_event_id, expected_event_type)."""
		raise NotImplementedError

	def setup_inputs(self):
		"""Return (team, setup_data) for setup_payment_method."""
		raise NotImplementedError

	def stub_setup(self):
		"""Context manager stubbing the SDK so setup returns a reference."""
		raise NotImplementedError

	def validation_inputs(self):
		"""Return a payment_method object for validate_payment_method."""
		raise NotImplementedError

	def stub_validation_success(self):
		raise NotImplementedError

	def stub_credentials_valid(self):
		"""Context manager: the SDK accepts a validate_credentials read and
		returns an account whose currency is `expected_account_currency()`."""
		raise NotImplementedError

	def stub_credentials_invalid(self):
		"""Context manager: the SDK rejects the credentials (auth error)."""
		raise NotImplementedError

	def expected_account_currency(self):
		"""Currency validate_credentials should report (or None if the gateway
		does not expose one)."""
		raise NotImplementedError

	# --- contract -----------------------------------------------------------

	def test_validate_credentials_returns_account_identity(self):
		adapter = self.make_adapter()
		with self.stub_credentials_valid():
			identity = adapter.validate_credentials()
		self.assertIsInstance(identity, dict)
		self.assertTrue(identity.get("account_id"))
		self.assertEqual(identity.get("currency"), self.expected_account_currency())

	def test_validate_credentials_raises_on_bad_keys(self):
		from central.billing.gateways.base import GatewayAuthError

		adapter = self.make_adapter()
		with self.stub_credentials_invalid():
			with self.assertRaises(GatewayAuthError):
				adapter.validate_credentials()

	def test_setup_payment_method_returns_client_handles(self):
		adapter = self.make_adapter()
		team, setup_data = self.setup_inputs()
		with self.stub_setup():
			result = adapter.setup_payment_method(team, setup_data)
		self.assertIsInstance(result, dict)
		self.assertTrue(result)  # carries at least one client-side handle

	def test_validate_payment_method_true_when_live(self):
		adapter = self.make_adapter()
		with self.stub_validation_success():
			self.assertTrue(adapter.validate_payment_method(self.validation_inputs()))

	def test_successful_charge_returns_captured(self):
		adapter = self.make_adapter()
		invoice, method, key = self.make_charge_inputs()
		with self.charge_succeeds(txn_id="txn_ok"):
			result = adapter.charge(invoice, method, key)
		self.assertTrue(result.success)
		self.assertEqual(result.status, "captured")
		self.assertEqual(result.gateway_transaction_id, "txn_ok")

	def test_declined_charge_is_a_failure_not_an_exception(self):
		adapter = self.make_adapter()
		invoice, method, key = self.make_charge_inputs()
		with self.charge_declines(code="card_declined"):
			result = adapter.charge(invoice, method, key)
		self.assertFalse(result.success)
		self.assertEqual(result.status, "failed")
		self.assertEqual(result.failure_code, "card_declined")

	def test_timeout_raises_gateway_timeout_and_forwards_idempotency_key(self):
		from central.billing.gateways.base import GatewayTimeout

		adapter = self.make_adapter()
		invoice, method, key = self.make_charge_inputs()
		with self.charge_times_out():
			with self.assertRaises(GatewayTimeout):
				adapter.charge(invoice, method, key)
		# Retry safety: the same key reached the gateway so a retry dedupes.
		self.assertEqual(self.captured_idempotency_key(), key)

	def test_refund_returns_completed_result(self):
		adapter = self.make_adapter()
		payment_attempt, amount, reason = self.make_refund_inputs()
		with self.refund_succeeds(refund_id="rfnd_ok"):
			result = adapter.refund(payment_attempt, amount, reason)
		self.assertTrue(result.success)
		self.assertEqual(result.status, "completed")
		self.assertEqual(result.gateway_refund_id, "rfnd_ok")

	def test_parse_webhook_event_normalises_id_and_type(self):
		adapter = self.make_adapter()
		payload, headers, expected_id, expected_type = self.parse_event_inputs()
		event = adapter.parse_webhook_event(payload, headers)
		self.assertEqual(event.gateway_event_id, expected_id)
		self.assertEqual(event.event_type, expected_type)

	def test_valid_signature_is_accepted(self):
		adapter = self.make_adapter()
		with self.signature_valid():
			self.assertTrue(adapter.verify_webhook_signature(b'{"id":"evt_1"}', self.webhook_headers()))

	def test_invalid_signature_is_rejected(self):
		adapter = self.make_adapter()
		with self.signature_invalid():
			self.assertFalse(adapter.verify_webhook_signature(b'{"id":"evt_1"}', self.webhook_headers()))
