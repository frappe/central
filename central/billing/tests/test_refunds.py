# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Refunds — full->source, partial->wallet (issue #15)."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe

from central.billing.catalog import subscriptions
from central.billing.gateways.base import RefundResult
from central.billing.payments import refunds
from central.billing.revenue import credits, invoicing
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	complete_billing_profile,
	ensure_atlas_instance,
	ensure_team,
	make_plan,
)

TEAM = "team-refund"
CLUSTER = "ap-south-1"
PLAN = "bundle-refund-test"
GATEWAY = "GW-Test-Stripe"


@contextmanager
def stub_refund(success=True, refund_id="rfnd_1"):
	adapter = MagicMock()
	adapter.refund.return_value = RefundResult(
		success=success, status="Completed" if success else "Failed", gateway_refund_id=refund_id
	)
	with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
		yield adapter


class RefundTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		ensure_atlas_instance(CLUSTER)
		complete_billing_profile(TEAM, currency="INR")  # so a provisioned segment is rated
		make_plan(PLAN)
		make_stripe_gateway(GATEWAY)
		self._purge()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Refund", "Payment Attempt", "Invoice", "Credit Ledger Entry"):
			frappe.db.delete(dt, {"team": TEAM})
		frappe.db.delete("Credit Wallet", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.commit()

	def _paid_invoice_with_attempt(self, total=1000):
		inv = frappe.get_doc(
			{
				"doctype": "Invoice", "team": TEAM, "invoice_type": "Billable", "status": "Paid",
				"period_start": "2026-05-01", "period_end": "2026-05-31", "currency": "INR",
				"subtotal": total, "total": total, "expected_collection": total, "amount_paid": total,
			}
		).insert(ignore_permissions=True).name
		attempt = frappe.get_doc(
			{
				"doctype": "Payment Attempt", "invoice": inv, "team": TEAM, "gateway": GATEWAY,
				"amount": total, "currency": "INR", "status": "Captured",
				"gateway_transaction_id": "pi_paid",
			}
		).insert(ignore_permissions=True).name
		return inv, attempt


class TestFullDispute(RefundTestBase):
	def test_full_refund_to_source_invoice_stays_paid(self):
		inv, attempt = self._paid_invoice_with_attempt(1000)
		with stub_refund(success=True, refund_id="rfnd_full") as adapter:
			refund = refunds.full_dispute(attempt, reason="fraud dispute")

		adapter.refund.assert_called_once()
		self.assertEqual(refund.destination, "Source")
		self.assertEqual(refund.amount, 1000.0)
		self.assertEqual(refund.status, "Completed")
		self.assertEqual(refund.gateway_refund_id, "rfnd_full")
		# Invoice stays Paid (no 'Refunded' state); the attempt is marked refunded.
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Paid")
		self.assertEqual(frappe.db.get_value("Payment Attempt", attempt, "status"), "Refunded")

	def test_failed_gateway_refund_is_recorded(self):
		inv, attempt = self._paid_invoice_with_attempt(1000)
		with stub_refund(success=False):
			refund = refunds.full_dispute(attempt)
		self.assertEqual(refund.status, "Failed")
		self.assertEqual(frappe.db.get_value("Payment Attempt", attempt, "status"), "Captured")

	def test_refund_only_on_captured_charge(self):
		inv, attempt = self._paid_invoice_with_attempt(1000)
		frappe.db.set_value("Payment Attempt", attempt, "status", "Failed")
		with self.assertRaises(frappe.ValidationError):
			refunds.full_dispute(attempt)


class TestPartialOvercharge(RefundTestBase):
	def test_partial_overcharge_credits_the_wallet(self):
		inv, attempt = self._paid_invoice_with_attempt(1000)
		# No gateway round-trip for a wallet credit.
		with stub_refund() as adapter:
			refund = refunds.partial_overcharge(attempt, amount=150, reason="overcharge")
			adapter.refund.assert_not_called()

		self.assertEqual(refund.destination, "Wallet")
		self.assertEqual(refund.status, "Completed")
		self.assertEqual(credits.get_balance(TEAM)["balance"], 150)
		# The credit is sourced from the Refund and applies next cycle.
		entry = frappe.get_all(
			"Credit Ledger Entry",
			{"team": TEAM, "reference_type": "Refund", "reference_name": refund.name},
			["entry_type", "amount"],
		)
		self.assertEqual(entry[0]["entry_type"], "Credit")
		self.assertEqual(entry[0]["amount"], 150)
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Paid")

	def test_churning_customer_partial_to_source(self):
		inv, attempt = self._paid_invoice_with_attempt(1000)
		with stub_refund(success=True, refund_id="rfnd_part") as adapter:
			refund = refunds.partial_overcharge(attempt, amount=150, to_source=True)
			adapter.refund.assert_called_once()
		self.assertEqual(refund.destination, "Source")
		self.assertEqual(credits.get_balance(TEAM)["balance"], 0)  # not wallet


class TestSymmetry(RefundTestBase):
	def test_refund_is_gateway_agnostic(self):
		# The module calls adapter.refund regardless of gateway — symmetric.
		inv, attempt = self._paid_invoice_with_attempt(500)
		frappe.db.set_value("Payment Attempt", attempt, "gateway", GATEWAY)
		with stub_refund(success=True, refund_id="rfnd_x") as adapter:
			refunds.full_dispute(attempt)
		args = adapter.refund.call_args.args
		self.assertEqual(args[1], 500.0)  # amount forwarded to the adapter


class TestPrePaymentCorrection(RefundTestBase):
	def test_cancel_and_reissue_does_not_mutate_line_items(self):
		# An Open invoice is corrected by cancel + reissue, not by editing. Creating the
		# subscription opens its billing segment (ADR 0010 — the ledger is the lock).
		sub = subscriptions.create_subscription(
			team=TEAM, cluster=CLUSTER, plan=PLAN, billing_cycle="Monthly", start_date="2026-06-01"
		).name
		first = invoicing.generate_draft_invoice(sub, "2026-06-01", "2026-06-30")

		reissued = invoicing.reissue_invoice(first, reason="wrong cluster")
		self.assertNotEqual(reissued, first)
		self.assertEqual(frappe.db.get_value("Invoice", first, "status"), "Cancelled")
		self.assertEqual(frappe.db.get_value("Invoice", reissued, "status"), "Draft")

	def test_cannot_cancel_a_paid_invoice(self):
		inv, _ = self._paid_invoice_with_attempt(1000)
		with self.assertRaises(frappe.ValidationError):
			invoicing.cancel_invoice(inv)
