# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Agentless provisioning opens the billing segment (ADR 0006 + ADR 0010).

There is no Subscription Agent and no plan push; Central provisions a resource and
opens its authoritative billing segment (the `Created` Subscription Change — the
price-lock itself, ADR 0010) at the catalog rate, so the rate shown is the rate
locked with no reconciliation gap.
"""

import frappe

from central.billing.catalog import subscriptions
from central.billing.catalog.subscriptions import active_segment_for_resource
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	complete_billing_profile,
	ensure_atlas_instance,
	ensure_team,
	make_plan,
)

TEAM = "team-provision"
PLAN = "bundle-provision"
CLUSTER = "ap-south-1"


class TestProvisionOpensSegment(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		complete_billing_profile(TEAM, currency="INR")
		ensure_atlas_instance(CLUSTER)
		make_plan(PLAN)  # INR catalog rate 3200
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.delete("Asset", {"team": TEAM})
		frappe.db.commit()

	def test_provision_opens_segment_at_catalog_rate(self):
		res = subscriptions.provision_subscription(TEAM, CLUSTER, PLAN)

		self.assertTrue(res["resource_id"])
		self.assertEqual(res["currency"], "INR")
		self.assertEqual(res["shown_rate"], 3200)

		# Provisioning opened the resource's billing segment — no agent push, no lock.
		seg = active_segment_for_resource(res["resource_id"])
		self.assertIsNotNone(seg)
		self.assertEqual(seg.plan, PLAN)
		self.assertEqual(seg.currency, "INR")
		# Rate shown == rate locked == Central's catalog rate.
		self.assertEqual(float(seg.locked_rate), 3200)

	def test_provision_segment_drives_invoice_generation(self):
		from central.billing.revenue import invoicing

		res = subscriptions.provision_subscription(TEAM, CLUSTER, PLAN, start_date="2026-06-01")
		name = invoicing.generate_draft_invoice(res["subscription"], "2026-06-01", "2026-06-30")
		inv = frappe.get_doc("Invoice", name)
		# A full June on the locked ₹3200 plan → a non-zero draft generated straight
		# from Central's own billing segment, with no agent in the loop.
		self.assertEqual(inv.status, "Draft")
		self.assertGreater(inv.subtotal, 0)
		self.assertTrue(inv.items)
