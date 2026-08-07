# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""What a price change actually reaches.

The misconception this whole tool exists to correct: raising a catalog rate does not
reprice a running subscription. The rate was snapshotted when the resource was
provisioned, and billing reads that snapshot until the customer resizes.
"""

import frappe
from central.billing.catalog import pricing
from central.billing.projection import repricing, scenario
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	ensure_team,
	make_billing_subscription,
	make_metered_plan,
	make_plan,
)

TEAM = "team-repricing"
CLUSTER = "ap-south-1"
PLAN = "bundle-repricing"
TODAY = "2026-08-06"


class TestTheRateSeam(IntegrationTestCase):
	def setUp(self):
		make_plan(PLAN, rates=[{"cluster": "", "currency": "INR", "rate": 1000}])
		frappe.db.commit()

	def test_without_an_override_the_published_rate_is_read(self):
		rows = pricing.get_catalog_rates("Plan", PLAN)
		self.assertEqual(resolve(rows), 1000.0)

	def test_a_percentage_override_is_read_instead(self):
		with pricing.overridden_rates([
			{"priced_doctype": "Plan", "priced_for": PLAN, "percent": 20}
		]):
			self.assertEqual(resolve(pricing.get_catalog_rates("Plan", PLAN)), 1200.0)

	def test_a_flat_override_replaces_the_rate(self):
		with pricing.overridden_rates([
			{"priced_doctype": "Plan", "priced_for": PLAN, "rate": 250}
		]):
			self.assertEqual(resolve(pricing.get_catalog_rates("Plan", PLAN)), 250.0)

	def test_an_override_for_another_plan_is_ignored(self):
		with pricing.overridden_rates([
			{"priced_doctype": "Plan", "priced_for": "some-other-plan", "percent": 50}
		]):
			self.assertEqual(resolve(pricing.get_catalog_rates("Plan", PLAN)), 1000.0)

	def test_a_currency_narrowed_override_leaves_other_currencies_alone(self):
		with pricing.overridden_rates([
			{"priced_doctype": "Plan", "priced_for": PLAN, "currency": "USD", "percent": 99}
		]):
			self.assertEqual(resolve(pricing.get_catalog_rates("Plan", PLAN)), 1000.0)

	def test_the_published_rate_is_never_written(self):
		# Asking what a price rise would do must not publish one.
		with pricing.overridden_rates([
			{"priced_doctype": "Plan", "priced_for": PLAN, "percent": 20}
		]):
			pricing.get_catalog_rates("Plan", PLAN)
		stored = frappe.db.get_value(
			"Catalog Rate", {"priced_doctype": "Plan", "priced_for": PLAN}, "rate"
		)
		self.assertEqual(frappe.utils.flt(stored), 1000.0)

	def test_the_override_lifts_when_the_block_ends(self):
		with pricing.overridden_rates([
			{"priced_doctype": "Plan", "priced_for": PLAN, "percent": 20}
		]):
			pass
		self.assertEqual(resolve(pricing.get_catalog_rates("Plan", PLAN)), 1000.0)


def resolve(rows):
	return pricing.resolve_rate(rows, "INR", None)


class TestClassification(IntegrationTestCase):
	def test_a_rate_locked_before_the_change_is_grandfathered(self):
		line = {"amount": 100, "derivation": {"locked_rate": 1000, "rate_locked_at": "2026-01-01 00:00:00"}}
		self.assertEqual(repricing.classify(line, "2026-09-01"), repricing.GRANDFATHERED)

	def test_a_rate_locked_after_the_change_is_repriced(self):
		line = {"amount": 100, "derivation": {"locked_rate": 1200, "rate_locked_at": "2026-09-15 00:00:00"}}
		self.assertEqual(repricing.classify(line, "2026-09-01"), repricing.REPRICED)

	def test_the_clamped_billing_window_is_never_mistaken_for_the_locking_date(self):
		# segment_from is clamped to the period, so a resource provisioned in March reads
		# as opening on 1 September when September is projected. Classifying on it would
		# call every long-running subscription newly priced — the exact opposite of true.
		line = {
			"amount": 100,
			"derivation": {
				"segment_from": "2026-09-01 00:00:00",
				"rate_locked_at": "2026-03-01 00:00:00",
				"locked_rate": 1000,
			},
		}
		self.assertEqual(repricing.classify(line, "2026-09-01"), repricing.GRANDFATHERED)

	def test_a_live_priced_family_is_always_repriced(self):
		# Depreciating storage is the deliberate exception to grandfathering: it reads
		# today's catalog every period, so a change reaches it at once.
		line = {"amount": 50, "derivation": {"rate_source": "current catalog rate"}}
		self.assertEqual(repricing.classify(line), repricing.REPRICED)

	def test_terms_locked_at_ingest_are_grandfathered(self):
		line = {"amount": 50, "derivation": {"rate_source": "locked at ingest"}}
		self.assertEqual(repricing.classify(line), repricing.GRANDFATHERED)

	def test_the_split_counts_money_and_resources_on_each_side(self):
		lines = [
			{"amount": 1000, "subscription_resource": "a",
			 "derivation": {"locked_rate": 1000, "rate_locked_at": "2026-01-01 00:00:00"}},
			{"amount": 500, "subscription_resource": "b",
			 "derivation": {"locked_rate": 500, "rate_locked_at": "2026-01-01 00:00:00"}},
			{"amount": 40, "subscription_resource": "c",
			 "derivation": {"rate_source": "current catalog rate"}},
		]
		out = repricing.split(lines, "INR", "2026-09-01")
		self.assertEqual(out["grandfathered"], 1500.0)
		self.assertEqual(out["repriced"], 40.0)
		self.assertEqual(out["grandfathered_resources"], 2)
		self.assertEqual(out["repriced_resources"], 1)


class RepricingTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		make_plan(PLAN, rates=[{"cluster": "", "currency": "INR", "rate": 12000}])
		self._purge()
		self.sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		# Provisioned in March at 12,000 — the rate that follows it forever.
		add_segment(self.sub, "Created", 12000, "2026-03-01 00:00:00")
		frappe.db.commit()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for name in frappe.get_all("Billing Scenario", pluck="name"):
			frappe.delete_doc("Billing Scenario", name, force=True, ignore_permissions=True)
		frappe.db.delete("Invoice", {"team": TEAM})
		frappe.db.delete("Usage Rollup", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.delete("Asset", {"team": TEAM})
		frappe.db.commit()

	def _scenario(self, percent=20, effective_from="2026-09-01"):
		doc = frappe.get_doc(
			{
				"doctype": "Billing Scenario",
				"scenario_name": f"Raise VM prices {percent}%",
				"team": TEAM,
				"period_start": "2026-09-01",
				"months": 1,
				"outcome_mode": "Derived",
				"rate_overrides": [
					{
						"priced_doctype": "Plan",
						"priced_for": PLAN,
						"currency": "INR",
						"percent": percent,
						"effective_from": effective_from,
					}
				],
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		return doc


class TestTheHeadlineAnswer(RepricingTestBase):
	def test_a_twenty_percent_rise_changes_nothing_for_a_running_subscription(self):
		# The whole point. A naive model would report +20%; the real answer is zero,
		# because the rate was locked in March and billing reads that snapshot.
		out = scenario.compare(self._scenario(percent=20), today=TODAY)

		self.assertEqual(
			out["live"]["invoice"]["total"], out["altered"]["invoice"]["total"]
		)

	def test_the_output_says_why_rather_than_leaving_a_zero_to_be_doubted(self):
		out = scenario.compare(self._scenario(percent=20), today=TODAY)
		self.assertIn("No change this period", out["explanation"])
		self.assertIn("locked", out["explanation"])

	def test_the_revenue_is_reported_as_grandfathered(self):
		out = scenario.compare(self._scenario(percent=20), today=TODAY)
		split = out["repricing"]
		self.assertEqual(split["grandfathered"], 12000.0)
		self.assertEqual(split["repriced"], 0.0)
		self.assertEqual(split["grandfathered_resources"], 1)

	def test_the_delta_is_far_smaller_than_multiplying_the_book(self):
		out = scenario.compare(self._scenario(percent=20), today=TODAY)
		naive = out["live"]["invoice"]["total"] * 0.20
		actual = out["altered"]["invoice"]["total"] - out["live"]["invoice"]["total"]
		self.assertGreater(naive, 0)
		self.assertLess(actual, naive)


class TestLivePricedFamilies(RepricingTestBase):
	def setUp(self):
		super().setUp()
		make_plan(
			PLAN,
			rates=[{"cluster": "", "currency": "INR", "rate": 12000}],
			includes=[{"resource_type": "Transfer", "quantity": 100, "unit": "GB"}],
		)
		make_metered_plan(
			"meter-transfer-repricing",
			resource_type="Transfer",
			rates=[{"cluster": "", "currency": "INR", "rate": 1.0}],
			pricing_mode="Live",
		)
		frappe.get_doc(
			{
				"doctype": "Usage Rollup",
				"resource_id": frappe.db.get_value("Subscription", self.sub, "asset_id"),
				"team": TEAM,
				"cluster": CLUSTER,
				"resource_type": "Transfer",
				"meter_type": "Counter",
				"period_start": "2026-08-01 00:00:00",
				"period_end": "2026-08-28 23:59:59",
				"quantity": 300,
				"unit": "GB",
				"currency": "INR",
				"locked_allowance": 100,
				"locked_rate": 1.0,
				"idempotency_key": "reprice:2026-08",
				"sequence": 0,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

	def test_a_live_priced_add_on_does_move_with_the_catalog(self):
		# The deliberate exception to grandfathering, and the reason the split has two
		# sides rather than a blanket "nothing changes".
		doc = frappe.get_doc(
			{
				"doctype": "Billing Scenario",
				"scenario_name": "Raise transfer 50%",
				"team": TEAM,
				"period_start": "2026-09-01",
				"months": 1,
				"outcome_mode": "Derived",
				"rate_overrides": [
					{
						"priced_doctype": "Plan",
						"priced_for": "meter-transfer-repricing",
						"currency": "INR",
						"percent": 50,
						"effective_from": "2026-09-01",
					}
				],
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

		out = scenario.compare(doc, today=TODAY)
		self.assertGreater(
			out["altered"]["invoice"]["total"], out["live"]["invoice"]["total"]
		)
		self.assertIn("priced live", out["explanation"])
