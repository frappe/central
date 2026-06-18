# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Agentless provisioning writes the price-lock (ADR 0006).

There is no Subscription Agent and no plan push; Central provisions a resource and
records the authoritative runtime (the price-lock) itself, at the catalog rate —
so the rate shown is the rate locked, with no reconciliation gap.
"""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.catalog import subscriptions
from central.billing.tests.utils import complete_billing_profile, ensure_team, make_plan

TEAM = "team-provision"
PLAN = "bundle-provision"
CLUSTER = "ap-south-1"


class TestProvisionWritesLock(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		complete_billing_profile(TEAM, currency="INR")
		make_plan(PLAN)  # INR catalog rate 3200
		frappe.db.delete("Price Lock", {"team": TEAM})
		frappe.db.commit()

	def test_provision_writes_open_lock_at_catalog_rate(self):
		res = subscriptions.provision_subscription(TEAM, CLUSTER, PLAN)

		self.assertTrue(res["resource_id"])
		self.assertEqual(res["currency"], "INR")
		self.assertEqual(res["shown_rate"], 3200)

		lock = frappe.db.get_value(
			"Price Lock",
			{"team": TEAM, "resource_id": res["resource_id"]},
			["plan", "locked_rate", "central_rate", "discrepancy", "ended_at", "event_type"],
			as_dict=True,
		)
		self.assertIsNotNone(lock)  # provisioning wrote the lock — no agent push needed
		self.assertEqual(lock.plan, PLAN)
		self.assertEqual(lock.event_type, "subscribed")
		self.assertFalse(lock.ended_at)  # an open (live) lock
		# Rate shown == rate locked == Central's catalog rate: no discrepancy.
		self.assertEqual(float(lock.locked_rate), 3200)
		self.assertEqual(float(lock.central_rate), 3200)
		self.assertFalse(lock.discrepancy)

	def test_provision_lock_drives_invoice_generation(self):
		from central.billing.revenue import invoicing

		res = subscriptions.provision_subscription(
			TEAM, CLUSTER, PLAN, start_date="2026-06-01"
		)
		name = invoicing.generate_draft_invoice(res["subscription"], "2026-06-01", "2026-06-30")
		inv = frappe.get_doc("Invoice", name)
		# A full June on the locked ₹3200 plan → a non-zero draft generated straight
		# from Central's own price-lock, with no agent in the loop.
		self.assertEqual(inv.status, "Draft")
		self.assertGreater(inv.subtotal, 0)
		self.assertTrue(inv.items)
