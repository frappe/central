# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Derived outcomes: assert failure only where the state entails it."""

import frappe
from central.billing.projection import outcomes
from central.billing.revenue import credits
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import ensure_atlas_instance, ensure_team, make_plan, set_team_tier

TEAM = "team-projection-outcomes"
CLUSTER = "ap-south-1"
PLAN = "bundle-projection-outcomes"
GATEWAY = "GW-Test-Stripe"
DUE = "2026-10-08"
TODAY = "2026-08-06"


class OutcomeTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		ensure_atlas_instance(CLUSTER)
		make_plan(PLAN)
		make_stripe_gateway(GATEWAY)
		self._purge()
		set_team_tier(TEAM, level="t0", max_spend=50000)
		frappe.db.commit()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Invoice", "Payment Attempt", "Credit Ledger Entry"):
			frappe.db.delete(dt, {"team": TEAM})
		frappe.db.delete("Credit Wallet", {"team": TEAM})
		frappe.db.delete("Payment Method", {"team": TEAM})
		frappe.db.delete("Billing Profile", {"team": TEAM})
		frappe.db.commit()

	def _profile(self, mode="Stripe Auto", currency="INR"):
		# set_team_tier already provisions a profile, so this adjusts rather than inserts.
		if frappe.db.exists("Billing Profile", TEAM):
			frappe.db.set_value(
				"Billing Profile",
				TEAM,
				{"currency": currency, "country": "India", "collection_mode": mode},
			)
		else:
			frappe.get_doc(
				{
					"doctype": "Billing Profile",
					"team": TEAM,
					"currency": currency,
					"country": "India",
					"collection_mode": mode,
				}
			).insert(ignore_permissions=True)
		frappe.db.commit()

	def _card(self, expiry_month=12, expiry_year=2030, status="Active"):
		return (
			frappe.get_doc(
				{
					"doctype": "Payment Method",
					"team": TEAM,
					"gateway": GATEWAY,
					"method_type": "Card",
					"status": status,
					"gateway_method_id": "pm_card",
					"gateway_customer_id": "cus_1",
					"is_default": 1,
					"display_label": "Visa 4242",
					"expiry_month": expiry_month,
					"expiry_year": expiry_year,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _mandate(self, ceiling, reauth=0):
		return (
			frappe.get_doc(
				{
					"doctype": "Payment Method",
					"team": TEAM,
					"gateway": GATEWAY,
					"method_type": "UPI Autopay",
					"status": "Active",
					"gateway_method_id": "mandate_1",
					"mandate_max_amount": ceiling,
					"mandate_currency": "INR",
					"reauth_required": reauth,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _derive(self, amount=10000.0):
		return outcomes.derive(TEAM, amount, "INR", DUE, frappe.utils.getdate(TODAY))

	def _codes(self, amount=10000.0):
		return {f.finding for f in self._derive(amount)}


class TestSilenceWhenNothingIsEntailed(OutcomeTestBase):
	def test_a_healthy_autopay_team_yields_no_findings(self):
		# Nothing in the data settles whether the charge works, so nothing is claimed.
		self._profile()
		self._card()
		frappe.db.commit()
		self.assertEqual(self._derive(), [])


class TestNoWayToPay(OutcomeTestBase):
	def test_no_method_and_no_credits_is_reported_once(self):
		self._profile()
		frappe.db.commit()
		self.assertIn("no_settlement_source", self._codes())

	def test_credits_without_a_card_is_a_missing_method_not_a_dead_end(self):
		self._profile()
		credits.purchase(TEAM, 50000, "INR")
		frappe.db.commit()
		codes = self._codes()
		self.assertIn("no_active_method", codes)
		self.assertNotIn("no_settlement_source", codes)

	def test_an_expired_card_does_not_count_as_a_method(self):
		self._profile()
		self._card(status="Expired")
		frappe.db.commit()
		self.assertIn("no_settlement_source", self._codes())


class TestTheIndianThreshold(OutcomeTestBase):
	def test_an_emandate_bill_over_the_threshold_lands_in_action_required(self):
		self._profile(mode="E-Mandate")
		self._mandate(ceiling=100000)
		frappe.db.commit()
		self.assertIn("over_silent_threshold", self._codes(amount=15000.0))

	def test_under_the_threshold_is_charged_silently(self):
		self._profile(mode="E-Mandate")
		self._mandate(ceiling=100000)
		frappe.db.commit()
		self.assertNotIn("over_silent_threshold", self._codes(amount=14999.0))

	def test_the_threshold_does_not_apply_to_a_card_team(self):
		self._profile(mode="Stripe Auto")
		self._card()
		frappe.db.commit()
		self.assertNotIn("over_silent_threshold", self._codes(amount=99000.0))

	def test_deriving_never_trips_the_profile_into_action_required(self):
		# The real charge path trips the mode here as a side effect. Asking the question
		# must not move the team into a new mode.
		self._profile(mode="E-Mandate")
		self._mandate(ceiling=100000)
		frappe.db.commit()
		self._derive(amount=40000.0)
		self.assertEqual(
			frappe.db.get_value("Billing Profile", TEAM, "collection_mode"), "E-Mandate"
		)


class TestOnSessionModes(OutcomeTestBase):
	def test_manual_checkout_means_the_customer_must_act(self):
		self._profile(mode="Manual Checkout")
		self._card()
		frappe.db.commit()
		self.assertIn("on_session_mode", self._codes())

	def test_action_required_is_reported_too(self):
		self._profile(mode="Action Required")
		self._card()
		frappe.db.commit()
		self.assertIn("on_session_mode", self._codes())


class TestMandateCeiling(OutcomeTestBase):
	def test_a_bill_above_the_mandate_cap_would_be_refused(self):
		self._profile(mode="E-Mandate")
		self._mandate(ceiling=5000)
		frappe.db.commit()
		self.assertIn("over_mandate_cap", self._codes(amount=8000.0))

	def test_a_bill_within_the_cap_is_not_flagged(self):
		self._profile(mode="E-Mandate")
		self._mandate(ceiling=20000)
		frappe.db.commit()
		self.assertNotIn("over_mandate_cap", self._codes(amount=8000.0))

	def test_a_team_with_no_mandate_is_never_over_a_mandate_cap(self):
		# effective_cap falls back to the tier cap when no mandate exists, and an untiered
		# team reads as a ceiling of zero — which would flag everyone.
		self._profile()
		frappe.db.delete("Billing Profile", {"team": TEAM})
		self._profile()
		frappe.db.commit()
		self.assertNotIn("over_mandate_cap", self._codes(amount=99999.0))

	def test_a_mandate_awaiting_reauthorisation_is_reported(self):
		self._profile(mode="E-Mandate")
		self._mandate(ceiling=100000, reauth=1)
		frappe.db.commit()
		self.assertIn("mandate_reauth_pending", self._codes(amount=1000.0))


class TestExpiringCards(OutcomeTestBase):
	def test_a_card_expiring_before_the_charge_is_flagged(self):
		self._profile()
		self._card(expiry_month=9, expiry_year=2026)  # good through 30 Sep; charged 8 Oct
		frappe.db.commit()
		self.assertIn("card_expires", self._codes())

	def test_a_card_valid_through_the_charge_month_is_not_flagged(self):
		self._profile()
		self._card(expiry_month=10, expiry_year=2026)  # good through 31 Oct
		frappe.db.commit()
		self.assertNotIn("card_expires", self._codes())


class TestCreditsOnly(OutcomeTestBase):
	def test_a_wallet_that_cannot_cover_the_bill_is_a_shortfall(self):
		self._profile()
		credits.purchase(TEAM, 3000, "INR")
		frappe.db.commit()
		findings = {f.finding: f for f in self._derive(amount=10000.0)}
		self.assertIn("credits_shortfall", findings)
		self.assertIn("short by", findings["credits_shortfall"].detail)

	def test_a_wallet_that_covers_it_is_not_a_shortfall(self):
		self._profile()
		credits.purchase(TEAM, 20000, "INR")
		frappe.db.commit()
		self.assertNotIn("credits_shortfall", self._codes(amount=10000.0))

	def test_a_card_behind_the_wallet_means_no_shortfall_is_claimed(self):
		# With a card as backstop the team is not credits-only, so an uncovered balance
		# is not by itself a failure.
		self._profile()
		self._card()
		credits.purchase(TEAM, 100, "INR")
		frappe.db.commit()
		self.assertNotIn("credits_shortfall", self._codes(amount=10000.0))


class TestTheVerdict(OutcomeTestBase):
	def test_optimistic_entails_settlement_and_finds_nothing(self):
		v = outcomes.verdict(outcomes.OPTIMISTIC, [])
		self.assertEqual(v.entailed_branch, "if_paid_on_time")
		self.assertEqual(v.findings, [])

	def test_derived_with_findings_entails_the_unpaid_branch(self):
		v = outcomes.verdict(outcomes.DERIVED, [outcomes._finding("x", "y", "z")])
		self.assertEqual(v.entailed_branch, "if_never_paid")

	def test_derived_without_findings_entails_neither(self):
		# Silence is not a prediction of success — the question is genuinely open.
		self.assertIsNone(outcomes.verdict(outcomes.DERIVED, []).entailed_branch)

	def test_an_assumed_outcome_follows_the_operator(self):
		self.assertEqual(
			outcomes.verdict(outcomes.ASSUMED, [], assume="pays_on_time").entailed_branch,
			"if_paid_on_time",
		)
		self.assertEqual(
			outcomes.verdict(outcomes.ASSUMED, [], assume="never_pays").entailed_branch,
			"if_never_paid",
		)

	def test_the_mode_is_always_reported_back(self):
		for mode in outcomes.MODES:
			self.assertEqual(outcomes.verdict(mode, []).mode, mode)
