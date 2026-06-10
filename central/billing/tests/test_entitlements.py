# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.catalog.entitlements import evaluate_tier, get_ladder, recompute_trust_tier
from central.billing.tests.utils import ensure_team

LADDER = [
	{"tier": "t0", "sequence": 0, "is_default": 1, "max_spend": 100, "max_resource_count": 1,
	 "min_paid_invoices": 0, "min_cumulative_paid": 0},
	{"tier": "t1", "sequence": 1, "max_spend": 300, "max_resource_count": 5,
	 "min_paid_invoices": 3, "min_cumulative_paid": 300},
	{"tier": "t2", "sequence": 2, "max_spend": 1000, "max_resource_count": 20,
	 "min_paid_invoices": 6, "min_cumulative_paid": 1000},
]


def make_ladder():
	for level in LADDER:
		if frappe.db.exists("Trust Tier Level", level["tier"]):
			frappe.delete_doc("Trust Tier Level", level["tier"], force=True)
		frappe.get_doc({"doctype": "Trust Tier Level", "__newname": level["tier"], **level}).insert(
			ignore_permissions=True
		)


class TestEvaluateTier(IntegrationTestCase):
	def setUp(self):
		make_ladder()

	def test_picks_highest_qualifying_tier(self):
		levels = get_ladder()
		self.assertEqual(evaluate_tier(6, 1000, levels).tier, "t2")
		self.assertEqual(evaluate_tier(3, 300, levels).tier, "t1")
		self.assertEqual(evaluate_tier(0, 0, levels).tier, "t0")

	def test_partial_threshold_does_not_promote(self):
		levels = get_ladder()
		# 3 paid invoices but only $50 cumulative — t1 needs both.
		self.assertEqual(evaluate_tier(3, 50, levels).tier, "t0")


class TestRecomputeTrustTier(IntegrationTestCase):
	def setUp(self):
		make_ladder()
		ensure_team("team-entitle")
		if frappe.db.exists("Trust Tier", "team-entitle"):
			frappe.delete_doc("Trust Tier", "team-entitle", force=True)

	def test_promotion_fires_and_records_basis(self):
		tier = recompute_trust_tier("team-entitle", paid_invoice_count=3, cumulative_paid=300)
		self.assertEqual(tier.tier, "t1")
		self.assertEqual(tier.max_spend, 300)
		self.assertTrue(tier.promoted_at)
		self.assertTrue(tier.promotion_basis)

	def test_manual_override_is_exempt(self):
		recompute_trust_tier("team-entitle", paid_invoice_count=6, cumulative_paid=1000)  # t2
		frappe.db.set_value("Trust Tier", "team-entitle", "manual_override", 1)

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
