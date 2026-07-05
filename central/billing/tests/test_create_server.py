# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Provisioning a server from a preset bundle records its Subscription.

Regression: `create_server` used to create the Atlas VM but never open the billing
contract, so a bundle-provisioned server had no Subscription and no price-lock — the
plan it was bought on was lost. It now records the Subscription like the composed
path does (ADR 0006/0010)."""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api import servers
from central.billing.catalog import subscriptions
from central.billing.tests.utils import (
	complete_billing_profile,
	ensure_atlas_instance,
	ensure_team,
	make_plan,
)

TEAM = "team-create-server"
REGION = "ap-south-1"
VM_ID = "vm-create-server-test"


class TestCreateServerRecordsSubscription(IntegrationTestCase):
	def setUp(self):
		ensure_atlas_instance(REGION)
		ensure_team(TEAM)
		complete_billing_profile(TEAM, currency="INR")
		# The preset provision path opens the price-lock at the catalog rate; it does
		# not enforce headroom, so no trust tier is needed here.
		self.plan = make_plan(
			"bundle-create-server", rates=[{"cluster": "", "currency": "INR", "rate": 1500}]
		)
		self._clear_team_subscriptions()
		frappe.set_user("Administrator")

	def _clear_team_subscriptions(self):
		for name in frappe.get_all("Subscription", filters={"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": name})
			frappe.delete_doc("Subscription", name, force=True)
		if frappe.db.exists("Asset", VM_ID):
			frappe.delete_doc("Asset", VM_ID, force=True)

	def _create_from_bundle(self, plan):
		"""Call the endpoint with Atlas stubbed to return our fixed VM id."""
		fake_client = MagicMock()
		fake_client.create_vm.return_value = {"name": VM_ID}
		with patch.object(servers.AtlasClient, "for_region", return_value=fake_client):
			return servers.create_server(
				team=TEAM, region=REGION, title="web-1", plan=plan,
				vcpus=2, memory_megabytes=4096, disk_gigabytes=40,
			)

	def test_bundle_provision_records_subscription_and_lock(self):
		out = self._create_from_bundle(self.plan)

		self.assertEqual(out["resource_id"], VM_ID)
		self.assertTrue(out["subscription"])

		sub = frappe.get_doc("Subscription", out["subscription"])
		self.assertEqual(sub.team, TEAM)
		self.assertEqual(sub.plan, self.plan)  # the bundle is recorded
		self.assertEqual(sub.pricing_mode, "Preset")
		self.assertEqual(sub.asset_id, VM_ID)  # linked to the provisioned VM

		# The opening segment IS the price-lock (ADR 0010) at the catalog rate.
		seg = subscriptions.current_segment_rate(sub.name)
		self.assertEqual(seg, 1500)

	def test_raw_size_without_plan_provisions_without_subscription(self):
		# Back-compat: a call with no plan still creates a VM and records nothing.
		out = self._create_from_bundle(None)

		self.assertEqual(out["resource_id"], VM_ID)
		self.assertIsNone(out["subscription"])
		self.assertFalse(frappe.db.exists("Subscription", {"asset_id": VM_ID}))

	def test_refused_without_a_billing_profile(self):
		# A team with no billing profile can't create servers — it must set one up
		# first (a server bills the team). Atlas is never touched.
		noprofile = "team-create-server-noprofile"
		ensure_team(noprofile)
		frappe.db.delete("Billing Profile", {"team": noprofile})
		fake_client = MagicMock()
		with patch.object(servers.AtlasClient, "for_region", return_value=fake_client):
			with self.assertRaises(frappe.ValidationError):
				servers.create_server(team=noprofile, region=REGION, title="web-1", plan=self.plan)
		fake_client.create_vm.assert_not_called()
