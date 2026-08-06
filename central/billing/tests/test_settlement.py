# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Credit application waterfall + wallet gating (issue #11)."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe

from central.billing.catalog import subscriptions
from central.billing.gateways.base import PaymentResult
from central.billing.payments import settlement
from central.billing.payments.settlement import (
	can_accept_spend,
	credit_forecast,
	effective_spend_cap,
	ensure_settlement_source,
	settlement_sources,
)
from central.billing.revenue import credits, invoicing
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import ensure_atlas_instance, ensure_team, make_plan, set_team_tier

TEAM = "team-waterfall"
CLUSTER = "ap-south-1"
PLAN = "bundle-waterfall-test"
GATEWAY = "GW-Test-Stripe"


@contextmanager
def stub_adapter(success=True, txn_id="pi_x"):
	adapter = MagicMock()
	adapter.charge.return_value = PaymentResult(
		success=success,
		status="Captured" if success else "Failed",
		gateway_transaction_id=txn_id if success else None,
		failure_code=None if success else "card_declined",
	)
	with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
		yield adapter


def set_tier(team, max_spend):
	set_team_tier(team, level="t0", max_spend=max_spend)


class SettlementTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		ensure_atlas_instance(CLUSTER)
		make_plan(PLAN)
		make_stripe_gateway(GATEWAY)
		self._purge()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Invoice", "Payment Attempt", "Credit Ledger Entry"):
			frappe.db.delete(dt, {"team": TEAM})
		frappe.db.delete("Credit Wallet", {"team": TEAM})
		for pm in frappe.get_all("Payment Method", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Payment Method", {"name": pm})
		frappe.db.delete("Billing Profile", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.commit()

	def _card(self):
		return (
			frappe.get_doc(
				{
					"doctype": "Payment Method",
					"team": TEAM,
					"gateway": GATEWAY,
					"method_type": "Card",
					"status": "Active",
					"gateway_method_id": "pm_card",
					"gateway_customer_id": "cus_1",
					"is_default": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _subscription(self, with_card=True):
		method = self._card() if with_card else None
		return subscriptions.create_subscription(
			team=TEAM,
			cluster=CLUSTER,
			plan=PLAN,
			billing_cycle="Monthly",
			default_payment_method=method,
			gateway=GATEWAY if with_card else None,
		).name

	def _draft(self, subscription, total):
		return (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"subscription": subscription,
					"status": "Draft",
					"period_start": "2026-06-01",
					"period_end": "2026-06-30",
					"currency": "INR",
					"subtotal": total,
					"total": total,
					"expected_collection": total,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)


class TestWaterfall(SettlementTestBase):
	def test_credits_first_then_card_for_remainder(self):
		sub = self._subscription(with_card=True)
		credits.purchase(TEAM, 400, "INR")
		inv = self._draft(sub, 1000)

		with stub_adapter(success=True, txn_id="pi_rem") as adapter:
			result = invoicing.open_and_collect(inv)

		invoice = frappe.get_doc("Invoice", inv)
		self.assertEqual(invoice.credit_applied, 400.0)
		self.assertEqual(invoice.expected_collection, 600.0)
		self.assertEqual(invoice.status, "Open")  # paid only on webhook
		# The card was charged the remainder, not the full total.
		self.assertEqual(adapter.charge.call_args.args[0].amount, 600.0)
		attempt = frappe.get_doc("Payment Attempt", result["charge"]["attempt"])
		self.assertEqual(attempt.amount, 600.0)
		self.assertEqual(attempt.status, "Captured")
		self.assertEqual(credits.get_balance(TEAM)["balance"], 0)

	def test_credits_cover_in_full_settles_without_charge(self):
		sub = self._subscription(with_card=True)
		credits.purchase(TEAM, 1000, "INR")
		inv = self._draft(sub, 1000)

		with stub_adapter() as adapter:
			result = invoicing.open_and_collect(inv)

		self.assertEqual(result["status"], "Paid")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Paid")
		adapter.charge.assert_not_called()  # no gateway round-trip
		self.assertEqual(frappe.db.count("Payment Attempt", {"invoice": inv}), 0)

	def test_residual_shortfall_leaves_invoice_open_not_stopped(self):
		sub = self._subscription(with_card=True)  # no credits
		inv = self._draft(sub, 1000)

		with stub_adapter(success=False):
			invoicing.open_and_collect(inv)

		# Declined remainder: invoice stays Open for dunning (#14), not stopped.
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Open")
		self.assertEqual(frappe.db.get_value("Subscription", sub, "account_standing"), "Current")
		attempt = frappe.get_all("Payment Attempt", {"invoice": inv}, ["status"])[0]
		self.assertEqual(attempt.status, "Failed")


class TestSettlementSources(SettlementTestBase):
	def test_onboarding_requires_a_settlement_source(self):
		with self.assertRaises(frappe.ValidationError):
			ensure_settlement_source(TEAM)  # neither card nor credits

		credits.purchase(TEAM, 100, "INR")
		ensure_settlement_source(TEAM)  # credits suffice — no raise

	def test_card_alone_is_a_valid_source(self):
		self._card()
		ensure_settlement_source(TEAM)
		sources = settlement_sources(TEAM)
		self.assertTrue(sources["has_autopay"])
		self.assertFalse(sources["credits_only"])


class TestWalletGating(SettlementTestBase):
	def test_credits_only_cap_is_min_tier_and_wallet(self):
		set_tier(TEAM, 100)
		credits.purchase(TEAM, 50, "INR")  # credits-only, wallet 50
		self.assertTrue(settlement_sources(TEAM)["credits_only"])
		self.assertEqual(effective_spend_cap(TEAM), 50)

		# Wallet above the tier cap → capped at the tier.
		credits.purchase(TEAM, 200, "INR")  # balance now 250
		self.assertEqual(effective_spend_cap(TEAM), 100)

	def test_autopay_team_follows_tier_directly(self):
		set_tier(TEAM, 100)
		self._card()  # autopay backstop, no credits
		self.assertEqual(effective_spend_cap(TEAM), 100)

	def test_provisioning_denied_beyond_wallet_coverage(self):
		set_tier(TEAM, 100)
		credits.purchase(TEAM, 50, "INR")  # credits-only
		self.assertTrue(can_accept_spend(TEAM, 40))
		self.assertFalse(can_accept_spend(TEAM, 60))  # beyond wallet coverage


class TestForecast(SettlementTestBase):
	def test_notify_fires_at_eighty_percent_of_balance(self):
		credits.purchase(TEAM, 100, "INR")
		self.assertFalse(credit_forecast(TEAM, 70, notify=False)["notify"])
		at_threshold = credit_forecast(TEAM, 80, notify=False)
		self.assertTrue(at_threshold["notify"])
		self.assertAlmostEqual(at_threshold["utilisation"], 0.8)

	def test_shortfall_reported_when_projection_exceeds_balance(self):
		credits.purchase(TEAM, 100, "INR")
		forecast = credit_forecast(TEAM, 130, notify=False)
		self.assertTrue(forecast["notify"])
		self.assertEqual(forecast["shortfall"], 30.0)

	def test_forecasting_without_notify_reaches_neither_the_customer_nor_the_socket(self):
		# The verdict still says a prompt is due; asking for the verdict must not send it.
		credits.purchase(TEAM, 100, "INR")
		with patch("central.billing.platform.notifications.notify") as notified, patch.object(
			frappe, "publish_realtime"
		) as published:
			self.assertTrue(credit_forecast(TEAM, 130, notify=False)["notify"])
			self.assertFalse(notified.called)
			self.assertFalse(published.called)

	def test_notify_true_still_sends(self):
		credits.purchase(TEAM, 100, "INR")
		with patch("central.billing.platform.notifications.notify") as notified:
			credit_forecast(TEAM, 130, notify=True)
			self.assertTrue(notified.called)
