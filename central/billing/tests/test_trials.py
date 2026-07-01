# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Free/trial as the entry trust tier — cost_report (issue #16)."""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.revenue import invoicing, credits
from central.billing.catalog import trials
from central.billing.catalog.entitlements import recompute_trust_tier
from central.billing.catalog.signing import generate_keypair
from central.billing.tests.test_entitlements import make_ladder
from central.billing.tests.utils import (
	add_segment,
	ensure_team,
	make_billing_subscription,
	make_plan,
)

TEAM = "team-trial"
CLUSTER = "ap-south-1"
PLAN = "bundle-trial-test"


class TrialTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		make_ladder()  # t0 (entry, default) / t1 / t2
		make_plan(PLAN)
		self._purge()
		# Asset-model subscription (seeds the cluster's Atlas Instance + the team's
		# INR Billing Profile, clears the auto 'Created' segment); the trust tier is
		# then pinned to the entry tier on that profile.
		self.sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		recompute_trust_tier(TEAM, paid_invoice_count=0, cumulative_paid=0)  # entry tier t0

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Invoice", "Credit Ledger Entry"):
			frappe.db.delete(dt, {"team": TEAM})
		frappe.db.delete("Credit Wallet", {"team": TEAM})
		frappe.db.delete("Billing Profile", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.delete("Asset", {"team": TEAM})
		frappe.db.delete("Entitlement Token", {"team": TEAM})
		frappe.db.commit()


class TestCostReportGeneration(TrialTestBase):
	def test_entry_tier_invoice_is_cost_report(self):
		self.assertTrue(trials.is_trial_team(TEAM))
		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")
		name = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		self.assertEqual(frappe.db.get_value("Invoice", name, "invoice_type"), "Cost Report")

	def test_cost_report_is_computed_but_not_charged(self):
		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")
		credits.purchase(TEAM, 500, "INR")  # even with a wallet, nothing is drawn
		name = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")

		result = invoicing.open_and_collect(name)
		inv = frappe.get_doc("Invoice", name)
		self.assertTrue(result.get("cost_report"))
		self.assertEqual(inv.status, "Open")
		self.assertEqual(inv.subtotal, 1000.0)  # computed
		self.assertEqual(inv.expected_collection, 0)  # but not charged
		self.assertEqual(inv.credit_applied, 0)  # credits untouched
		self.assertEqual(credits.get_balance(TEAM)["balance"], 500)
		self.assertEqual(frappe.db.count("Payment Attempt", {"invoice": name}), 0)


class TestConversion(TrialTestBase):
	def test_convert_to_paid_flips_type_and_keeps_resources(self):
		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")  # runs into July too
		# June: trial → cost_report.
		june = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		self.assertEqual(frappe.db.get_value("Invoice", june, "invoice_type"), "Cost Report")

		trials.convert_to_paid(TEAM)
		self.assertFalse(trials.is_trial_team(TEAM))

		# July invoice is billable; the resource's open segment is untouched (still running).
		july = invoicing.generate_draft_invoice(self.sub, "2026-07-01", "2026-07-31")
		self.assertEqual(frappe.db.get_value("Invoice", july, "invoice_type"), "Billable")
		from central.billing.catalog.subscriptions import current_segment_rate

		self.assertEqual(current_segment_rate(self.sub), 1000.0)
		self.assertEqual(
			frappe.db.get_value("Subscription", self.sub, "account_standing"), "Current"
		)


class TestSubsidyAndExpiry(TrialTestBase):
	def test_subsidy_total_sums_cost_report_invoices(self):
		# A far-future period isolates this global aggregate from seeded demo data.
		# Two run-segments in the team+cluster (1000 + 2000) — the consolidated draft
		# day-weights both over the full month.
		add_segment(self.sub, "Created", 1000, "2099-01-01 00:00:00")
		sub_b = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(sub_b, "Created", 2000, "2099-01-01 00:00:00")
		name = invoicing.generate_draft_invoice(self.sub, "2099-01-01", "2099-01-31")
		self.assertEqual(frappe.db.get_value("Invoice", name, "invoice_type"), "Cost Report")

		subsidy = trials.subsidy_total("2099-01-01", "2099-01-31")
		self.assertEqual(subsidy, 3000.0)  # 1000 + 2000, full month

	def test_expired_trial_emits_suspend_directive(self):
		priv, pub = generate_keypair()
		frappe.conf.entitlement_private_key = priv

		token = trials.expire_trial(TEAM)
		self.assertEqual(token["payload"]["suspend"], 1)
		self.assertEqual(frappe.db.get_value("Entitlement Token", token["name"], "suspend"), 1)
