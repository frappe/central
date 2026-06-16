from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.atlas import registry, sync_team_assets
from central.tests.test_iam import ensure_user


class TestAtlasSync(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._orig_stub = frappe.conf.get("atlas_use_stub_inventory")
		frappe.conf.atlas_use_stub_inventory = 1
		self.owner = ensure_user("sync.owner@example.test")
		self.outsider = ensure_user("sync.outsider@example.test")
		self.team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Sync Team",
				"owner_user": self.owner,
				"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
			}
		).insert()
		self.region = "blr-sync"
		if not frappe.db.exists("Atlas Instance", self.region):
			frappe.get_doc(
				{
					"doctype": "Atlas Instance",
					"region": self.region,
					"base_url": "https://atlas.example.test",
					"status": "Active",
					"api_key": "k",
					"api_secret": "s",
				}
			).insert()

	def tearDown(self):
		frappe.conf.atlas_use_stub_inventory = self._orig_stub
		frappe.set_user("Administrator")

	def test_sync_mirrors_inventory_into_assets(self):
		freshness = sync_team_assets(self.team.name)
		self.assertIn(self.region, freshness["synced"])
		self.assertEqual(freshness["stale"], [])

		vm = frappe.get_doc("Asset", "vm-blr-1")
		self.assertEqual(vm.team, self.team.name)
		self.assertEqual(vm.cluster, self.region)
		self.assertEqual(vm.status, "Running")
		self.assertTrue(vm.last_synced_at)

	def test_registry_returns_team_assets(self):
		result = registry(team=self.team.name)
		ids = {a["resource_id"] for a in result["assets"]}
		self.assertIn("vm-blr-1", ids)
		self.assertIn(self.region, result["synced"])

	def test_sync_is_failsoft_when_atlas_unreachable(self):
		frappe.conf.atlas_use_stub_inventory = 0
		with patch("central.atlas.AtlasClient.list_vms", side_effect=Exception("unreachable")):
			freshness = sync_team_assets(self.team.name)
		self.assertIn(self.region, freshness["stale"])
		self.assertEqual(freshness["synced"], [])

	def test_registry_blocked_for_non_member(self):
		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			registry(team=self.team.name)
