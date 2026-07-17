# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

from central.billing.catalog.entitlements import evaluate_tier, get_ladder, recompute_trust_tier
from central.billing.tests.utils import clear_team_tier, complete_billing_profile, ensure_team

# Money limits are INR here; make_ladder seeds them as the level's INR threshold.
LADDER = [
	{"tier": "t0", "sequence": 0, "is_default": 1, "max_spend": 100, "max_resource_count": 1,
	 "min_paid_invoices": 0, "min_cumulative_paid": 0},
	{"tier": "t1", "sequence": 1, "max_spend": 300, "max_resource_count": 5,
	 "min_paid_invoices": 3, "min_cumulative_paid": 300},
	{"tier": "t2", "sequence": 2, "max_spend": 1000, "max_resource_count": 20,
	 "min_paid_invoices": 6, "min_cumulative_paid": 1000},
]


def make_ladder():
	"""Seed the ladder in INR. The entry tier must price every supported currency
	(validation), so it carries INR + whatever gateways the site offers; higher
	rungs stay INR-only — which also leaves a USD team unable to climb past entry."""
	from central.billing.gateways.registry import supported_currencies

	# Hermetic: wipe the whole ladder first (including the shipped Beginner→Elite
	# fixtures) so get_ladder() resolves against exactly the t0/t1/t2 rungs these
	# tests assert on — an extra qualifying rung or a second entry tier would skew
	# evaluate_tier / recompute results.
	for name in frappe.get_all("Trust Tier Level", pluck="name"):
		frappe.delete_doc("Trust Tier Level", name, force=True)

	entry_currencies = sorted(set(supported_currencies()) | {"INR"})
	for level in LADDER:
		currencies = entry_currencies if level.get("is_default") else ["INR"]
		frappe.get_doc(
			{
				"doctype": "Trust Tier Level",
				"__newname": level["tier"],
				"tier": level["tier"],
				"sequence": level["sequence"],
				"is_default": level.get("is_default", 0),
				"max_resource_count": level["max_resource_count"],
				"min_paid_invoices": level["min_paid_invoices"],
				"thresholds": [
					{
						"currency": c,
						"max_spend": level["max_spend"],
						"min_cumulative_paid": level["min_cumulative_paid"],
					}
					for c in currencies
				],
			}
		).insert(ignore_permissions=True)


class TestEvaluateTier(IntegrationTestCase):
	def setUp(self):
		make_ladder()

	def test_picks_highest_qualifying_tier(self):
		levels = get_ladder()
		self.assertEqual(evaluate_tier(6, 1000, "INR", levels).tier, "t2")
		self.assertEqual(evaluate_tier(3, 300, "INR", levels).tier, "t1")
		self.assertEqual(evaluate_tier(0, 0, "INR", levels).tier, "t0")

	def test_partial_threshold_does_not_promote(self):
		levels = get_ladder()
		# 3 paid invoices but only 50 cumulative — t1 needs both.
		self.assertEqual(evaluate_tier(3, 50, "INR", levels).tier, "t0")

	def test_currency_without_a_threshold_row_falls_to_entry(self):
		levels = get_ladder()
		# The ladder only prices INR; a USD team can't climb past the entry tier.
		self.assertEqual(evaluate_tier(6, 1000, "USD", levels).tier, "t0")


class TestRecomputeTrustTier(IntegrationTestCase):
	def setUp(self):
		make_ladder()
		ensure_team("team-entitle")
		complete_billing_profile("team-entitle")  # currency = INR
		clear_team_tier("team-entitle")

	def test_promotion_fires_and_records_basis(self):
		tier = recompute_trust_tier("team-entitle", paid_invoice_count=3, cumulative_paid=300)
		self.assertEqual(tier.tier, "t1")
		self.assertEqual(tier.max_spend, 300)
		self.assertTrue(tier.promoted_at)
		self.assertTrue(tier.promotion_basis)

	def test_manual_override_is_exempt(self):
		recompute_trust_tier("team-entitle", paid_invoice_count=6, cumulative_paid=1000)  # t2
		frappe.db.set_value("Billing Profile", "team-entitle", "manual_override", 1)

		tier = recompute_trust_tier("team-entitle", paid_invoice_count=0, cumulative_paid=0)
		self.assertEqual(tier.tier, "t2")  # not demoted
		self.assertEqual(tier.max_spend, 1000)

	def test_demotion_lowers_cap_only(self):
		recompute_trust_tier("team-entitle", paid_invoice_count=6, cumulative_paid=1000)  # t2
		tier = recompute_trust_tier("team-entitle", paid_invoice_count=0, cumulative_paid=0)
		# Cap drops to entry; demotion limits growth, it does not stop running resources
		# (no suspend is issued here — that is a non-payment directive on the token).
		self.assertEqual(tier.tier, "t0")
		self.assertEqual(tier.max_spend, 100)
