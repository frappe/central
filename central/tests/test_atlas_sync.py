from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.atlas import ingest_event, reconcile, reconcile_atlas, refresh_assets, registry
from central.tests.test_iam import ensure_user


class TestAtlasMirror(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
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
		self.atlas_id = "atlas-blr-sync"
		if not frappe.db.exists("Atlas Instance", self.region):
			frappe.get_doc(
				{
					"doctype": "Atlas Instance",
					"region": self.region,
					"base_url": "https://atlas.example.test",
					"status": "Active",
					"atlas_id": self.atlas_id,
					"api_key": "k",
					"api_secret": "s",
				}
			).insert()
		else:
			frappe.db.set_value("Atlas Instance", self.region, "atlas_id", self.atlas_id)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _push(self, event_type, vm, occurred_at):
		return ingest_event(self.atlas_id, event_type, vm, occurred_at)

	# --- push -----------------------------------------------------------------

	def test_push_creates_then_updates_with_lww(self):
		self._push(
			"vm.created",
			{"name": "vm-1", "central_reference": self.team.name, "status": "Running"},
			"2026-06-18 10:00:00",
		)
		asset = frappe.get_doc("Asset", "vm-1")
		self.assertEqual(asset.team, self.team.name)
		self.assertEqual(asset.cluster, self.region)
		self.assertEqual(asset.status, "Running")

		# a newer event applies
		self._push(
			"vm.status_changed",
			{"name": "vm-1", "central_reference": self.team.name, "status": "Stopped"},
			"2026-06-18 10:05:00",
		)
		self.assertEqual(frappe.db.get_value("Asset", "vm-1", "status"), "Stopped")

		# a stale (older) event is ignored
		self._push(
			"vm.status_changed",
			{"name": "vm-1", "central_reference": self.team.name, "status": "Running"},
			"2026-06-18 09:00:00",
		)
		self.assertEqual(frappe.db.get_value("Asset", "vm-1", "status"), "Stopped")

	def test_push_from_unknown_atlas_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			ingest_event(
				"who-dis",
				"vm.created",
				{"name": "vm-x", "central_reference": self.team.name, "status": "Running"},
				"2026-06-18 10:00:00",
			)

	def test_push_skips_untenanted_vm(self):
		self._push("vm.created", {"name": "vm-op", "central_reference": None, "status": "Running"}, "2026-06-18 10:00:00")
		self.assertFalse(frappe.db.exists("Asset", "vm-op"))

	def test_vm_deleted_marks_terminated(self):
		self._push(
			"vm.created",
			{"name": "vm-2", "central_reference": self.team.name, "status": "Running"},
			"2026-06-18 10:00:00",
		)
		self._push("vm.deleted", {"name": "vm-2"}, "2026-06-18 11:00:00")
		self.assertEqual(frappe.db.get_value("Asset", "vm-2", "status"), "Terminated")

	# --- pull / reconcile -----------------------------------------------------

	def test_reconcile_upserts_present_and_terminates_missing(self):
		self._push(
			"vm.created",
			{"name": "gone", "central_reference": self.team.name, "status": "Running"},
			"2026-06-18 10:00:00",
		)
		instance = frappe.get_doc("Atlas Instance", self.region)
		pulled = [{"name": "vm-3", "central_reference": self.team.name, "status": "Stopped", "gateway_url": None}]
		with patch("central.atlas.AtlasClient.central_vms", return_value=pulled):
			reconcile_atlas(instance, self.team.name)
		self.assertEqual(frappe.db.get_value("Asset", "vm-3", "status"), "Stopped")
		self.assertEqual(frappe.db.get_value("Asset", "gone", "status"), "Terminated")

	def test_refresh_assets_reconciles_and_registry_lists(self):
		pulled = [{"name": "vm-4", "central_reference": self.team.name, "status": "Running", "gateway_url": None}]
		with patch("central.atlas.AtlasClient.central_vms", return_value=pulled):
			result = refresh_assets(team=self.team.name)
		self.assertIn(self.region, result["synced"])
		ids = {a["resource_id"] for a in registry(team=self.team.name)["assets"]}
		self.assertIn("vm-4", ids)

	def test_reconcile_is_failsoft_when_atlas_unreachable(self):
		with patch("central.atlas.AtlasClient.central_vms", side_effect=Exception("unreachable")):
			result = reconcile(team=self.team.name)
		self.assertIn(self.region, result["stale"])

	# --- read gate ------------------------------------------------------------

	def test_registry_blocked_for_non_member(self):
		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			registry(team=self.team.name)
