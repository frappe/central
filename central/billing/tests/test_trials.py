# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Entry-tier billing (issue #16).

Free trials are retired — every team is billable and receives welcome credits, so
an entry-tier team's invoice is Billable and settles from its wallet. The Cost
Report helpers (is_trial_team, convert_to_paid, expire_trial, subsidy_total) are
dormant, exercised here by hand until their separate cleanup."""

import frappe
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

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


class TestEntryTierBilling(TrialTestBase):
	def test_entry_tier_invoice_is_billable(self):
		# No free trials any more — the entry tier is just the lowest rung, so its
		# invoice is Billable (not a Cost Report that would never draw the credits).
		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")
		name = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		self.assertEqual(frappe.db.get_value("Invoice", name, "invoice_type"), "Billable")

	def test_entry_tier_bill_settles_from_welcome_credits(self):
		# Regression: an entry-tier team used to get a Cost Report that never drew its
		# credits, stranding it on an uncollectable Open invoice with a "Pay 0.00"
		# button. Now the bill is billable and the wallet settles it to Paid with no
		# card touched.
		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")
		credits.purchase(TEAM, 5000, "INR")  # welcome-credit stand-in, covers the bill
		name = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")

		invoicing.open_and_collect(name, collect=False)
		inv = frappe.get_doc("Invoice", name)
		self.assertEqual(inv.status, "Paid")
		self.assertEqual(inv.expected_collection, 0)  # credits cover it in full
		self.assertEqual(inv.credit_applied, inv.total)  # drawn from the wallet
		self.assertEqual(frappe.db.count("Payment Attempt", {"invoice": name}), 0)  # no card


class TestConversion(TrialTestBase):
	def test_convert_to_paid_promotes_tier_and_keeps_resources(self):
		# convert_to_paid is dormant (invoices are billable regardless now), but it
		# still promotes the tier off the entry rung without touching resources.
		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")  # runs into July too
		self.assertTrue(trials.is_trial_team(TEAM))

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
		# subsidy_total is dormant now (nothing emits Cost Reports), but it still sums
		# any that exist. Build two by hand in a far-future period — isolated from
		# seeded demo data — and check the aggregate.
		for subtotal in (1000.0, 2000.0):
			frappe.get_doc({
				"doctype": "Invoice", "team": TEAM, "invoice_type": "Cost Report",
				"status": "Open", "period_start": "2099-01-01", "period_end": "2099-01-31",
				"currency": "INR", "subtotal": subtotal, "total": subtotal,
			}).insert(ignore_permissions=True)

		subsidy = trials.subsidy_total("2099-01-01", "2099-01-31")
		self.assertEqual(subsidy, 3000.0)  # 1000 + 2000

	def test_expired_trial_emits_suspend_directive(self):
		priv, pub = generate_keypair()
		frappe.conf.entitlement_private_key = priv

		token = trials.expire_trial(TEAM)
		self.assertEqual(token["payload"]["suspend"], 1)
		self.assertEqual(frappe.db.get_value("Entitlement Token", token["name"], "suspend"), 1)
