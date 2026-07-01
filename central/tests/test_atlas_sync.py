from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.servers import refresh_assets, registry
from central.integrations.atlas import apply_event, ingest_event, reconcile, reconcile_atlas
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
		# The Atlas authenticates as its scoped service user; the sender (= cluster) is
		# resolved from that session, so the instance is keyed on service_user.
		self.service_user = ensure_user("atlas-blr-sync@example.test")
		if not frappe.db.exists("Atlas Instance", self.region):
			frappe.get_doc(
				{
					"doctype": "Atlas Instance",
					"region": self.region,
					"base_url": "https://atlas.example.test",
					"status": "Active",
					"service_user": self.service_user,
					"api_key": "k",
					"api_secret": "s",
				}
			).insert()
		else:
			frappe.db.set_value("Atlas Instance", self.region, "service_user", self.service_user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _push(self, event_type, vm, occurred_at):
		# ingest_event verifies the sender then queues the work; here we run the
		# worker (apply_event) directly to assert its mirror effect. The
		# verify-and-queue path is covered by the dispatch tests below.
		apply_event(self.region, event_type, vm, occurred_at)

	# --- push -----------------------------------------------------------------

	def test_push_creates_then_updates_with_lww(self):
		self._push(
			"vm.created",
			{"name": "vm-1", "team": self.team.name, "status": "Running"},
			"2026-06-18 10:00:00",
		)
		asset = frappe.get_doc("Asset", "vm-1")
		self.assertEqual(asset.team, self.team.name)
		self.assertEqual(asset.cluster, self.region)
		self.assertEqual(asset.status, "Running")

		# a newer event applies
		self._push(
			"vm.status_changed",
			{"name": "vm-1", "team": self.team.name, "status": "Stopped"},
			"2026-06-18 10:05:00",
		)
		self.assertEqual(frappe.db.get_value("Asset", "vm-1", "status"), "Stopped")

		# a stale (older) event is ignored
		self._push(
			"vm.status_changed",
			{"name": "vm-1", "team": self.team.name, "status": "Running"},
			"2026-06-18 09:00:00",
		)
		self.assertEqual(frappe.db.get_value("Asset", "vm-1", "status"), "Stopped")

	def test_push_from_unknown_atlas_is_refused(self):
		# A session that owns no Atlas Instance can't push events.
		frappe.set_user(self.outsider)
		try:
			with self.assertRaises(frappe.PermissionError):
				ingest_event(
					"vm.created",
					{"name": "vm-x", "team": self.team.name, "status": "Running"},
					"2026-06-18 10:00:00",
				)
		finally:
			frappe.set_user("Administrator")

	def test_push_skips_untenanted_vm(self):
		self._push("vm.created", {"name": "vm-op", "team": None, "status": "Running"}, "2026-06-18 10:00:00")
		self.assertFalse(frappe.db.exists("Asset", "vm-op"))

	def test_vm_deleted_marks_terminated(self):
		self._push(
			"vm.created",
			{"name": "vm-2", "team": self.team.name, "status": "Running"},
			"2026-06-18 10:00:00",
		)
		self._push("vm.deleted", {"name": "vm-2"}, "2026-06-18 11:00:00")
		self.assertEqual(frappe.db.get_value("Asset", "vm-2", "status"), "Terminated")

	def test_vm_resized_event_updates_mirror_shape(self):
		self._push(
			"vm.created",
			{"name": "vm-r", "team": self.team.name, "status": "Stopped",
			 "vcpus": 2, "memory_megabytes": 4096, "disk_gigabytes": 40},
			"2026-06-18 10:00:00",
		)
		# A resize leaves the VM Stopped, so no status_changed ever fires — the
		# vm.resized event is how the mirror learns the new shape.
		self._push(
			"vm.resized",
			{"name": "vm-r", "team": self.team.name, "status": "Stopped",
			 "vcpus": 4, "memory_megabytes": 16384, "disk_gigabytes": 80},
			"2026-06-18 10:05:00",
		)
		asset = frappe.get_doc("Asset", "vm-r")
		self.assertEqual((asset.vcpus, asset.memory_megabytes, asset.disk_gigabytes), (4, 16384, 80))

	def test_resize_vm_posts_run_doc_method_with_args(self):
		import json

		from central.integrations.atlas import AtlasClient

		client = AtlasClient(frappe.get_doc("Atlas Instance", self.region))
		with patch.object(AtlasClient, "client") as make_client:
			make_client.return_value.post_api.return_value = "task-9"
			task = client.resize_vm("vm-x", vcpus=4, memory_megabytes=16384, disk_gigabytes=80)
		self.assertEqual(task, "task-9")
		params = make_client.return_value.post_api.call_args.kwargs["params"]
		self.assertEqual((params["dt"], params["dn"], params["method"]), ("Virtual Machine", "vm-x", "resize"))
		self.assertEqual(
			json.loads(params["args"]),
			{"vcpus": 4, "memory_megabytes": 16384, "disk_gigabytes": 80},
		)

	# --- dispatch: verify synchronously, mirror in the background -------------

	def test_known_event_is_queued_not_applied_inline(self):
		vm = {"name": "vm-q", "team": self.team.name, "status": "Running"}
		frappe.set_user(self.service_user)
		try:
			with patch("frappe.enqueue") as enqueue:
				result = ingest_event("vm.created", vm, "2026-06-18 10:00:00")
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(result["queued"])
		enqueue.assert_called_once()
		# nothing written on the request thread — the worker does it
		self.assertFalse(frappe.db.exists("Asset", "vm-q"))

	def test_unknown_event_type_is_acked_without_queuing(self):
		frappe.set_user(self.service_user)
		try:
			with patch("frappe.enqueue") as enqueue:
				result = ingest_event("vm.rebooted", {"name": "vm-z"}, "2026-06-18 10:00:00")
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(result, {"ok": True, "queued": False})
		enqueue.assert_not_called()

	def test_mirror_recovers_when_exists_check_loses_insert_race(self):
		from central.central.doctype.asset.asset import Asset

		self._push("vm.created", {"name": "vm-race", "team": self.team.name, "status": "Pending"}, "2026-06-18 10:00:00")

		# Simulate the REPEATABLE READ race: a concurrent writer's exists-check misses
		# the row, so it takes the insert path and hits the duplicate key. mirror_vm
		# must recover by updating, not raise DuplicateEntryError.
		real_exists = frappe.db.exists

		def blind_to_asset(dt, *a, **k):
			return None if dt == "Asset" else real_exists(dt, *a, **k)

		with patch("frappe.db.exists", side_effect=blind_to_asset):
			Asset.mirror_vm(
				self.region,
				{"name": "vm-race", "team": self.team.name, "status": "Running"},
				occurred_at="2026-06-18 11:00:00",
			)
		self.assertEqual(frappe.db.get_value("Asset", "vm-race", "status"), "Running")

	# --- pull / reconcile -----------------------------------------------------

	def test_reconcile_upserts_present_and_terminates_missing(self):
		self._push(
			"vm.created",
			{"name": "gone", "team": self.team.name, "status": "Running"},
			"2026-06-18 10:00:00",
		)
		instance = frappe.get_doc("Atlas Instance", self.region)
		pulled = [{"name": "vm-3", "team": self.team.name, "status": "Stopped", "gateway_url": None}]
		with patch("central.integrations.atlas.AtlasClient.central_vms", return_value=pulled):
			reconcile_atlas(instance, self.team.name)
		self.assertEqual(frappe.db.get_value("Asset", "vm-3", "status"), "Stopped")
		self.assertEqual(frappe.db.get_value("Asset", "gone", "status"), "Terminated")

	def test_refresh_assets_reconciles_and_registry_lists(self):
		pulled = [{"name": "vm-4", "team": self.team.name, "status": "Running", "gateway_url": None}]
		with patch("central.integrations.atlas.AtlasClient.central_vms", return_value=pulled):
			result = refresh_assets(team=self.team.name)
		self.assertIn(self.region, result["synced"])
		ids = {a["resource_id"] for a in registry(team=self.team.name)["assets"]}
		self.assertIn("vm-4", ids)

	def test_reconcile_is_failsoft_when_atlas_unreachable(self):
		with patch("central.integrations.atlas.AtlasClient.central_vms", side_effect=Exception("unreachable")):
			result = reconcile(team=self.team.name)
		self.assertIn(self.region, result["stale"])

	# --- read gate ------------------------------------------------------------

	def test_registry_blocked_for_non_member(self):
		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			registry(team=self.team.name)
