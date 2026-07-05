from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.servers import refresh_assets, registry, start_server
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

	def test_bench_login_handoff_mirrors_and_is_write_once(self):
		# A bench VM reports its front door immediately, but the login URL + expiry only
		# arrive once Running (Atlas gates them on status).
		self._push(
			"vm.created",
			{"name": "vm-b", "team": self.team.name, "status": "Pending",
			 "gateway_url": "https://acme.blr1.frappe.dev"},
			"2026-06-18 10:00:00",
		)
		asset = frappe.get_doc("Asset", "vm-b")
		self.assertEqual(asset.gateway_url, "https://acme.blr1.frappe.dev")
		self.assertIsNone(asset.login_url)

		# The Running event carries the minted handoff — it lands on the mirror.
		self._push(
			"vm.status_changed",
			{"name": "vm-b", "team": self.team.name, "status": "Running",
			 "gateway_url": "https://acme.blr1.frappe.dev",
			 "login_url": "https://acme.blr1.frappe.dev/app?sid=abc",
			 "login_url_expires_at": "2026-06-18 10:05:00"},
			"2026-06-18 10:01:00",
		)
		asset.reload()
		self.assertEqual(asset.login_url, "https://acme.blr1.frappe.dev/app?sid=abc")
		self.assertEqual(str(asset.login_url_expires_at), "2026-06-18 10:05:00")

		# Write-once: a later status-only event (no login_url in the payload — e.g. the
		# reconcile shape before another Running) must not blank the stored handoff.
		self._push(
			"vm.status_changed",
			{"name": "vm-b", "team": self.team.name, "status": "Stopped",
			 "gateway_url": "https://acme.blr1.frappe.dev"},
			"2026-06-18 10:10:00",
		)
		asset.reload()
		self.assertEqual(asset.login_url, "https://acme.blr1.frappe.dev/app?sid=abc")

	def test_site_login_handoff_mirrors_and_is_write_once(self):
		# A self-serve Site's one-click login URL + expiry only arrive once Running
		# (Atlas gates them on status), same contract as the bench VM's.
		fqdn = "handoff.blr1.frappe.dev"
		self._push(
			"site.created",
			{"name": fqdn, "team": self.team.name, "subdomain": "handoff", "status": "Provisioning"},
			"2026-06-18 10:00:00",
		)
		site = frappe.get_doc("Site", fqdn)
		self.assertIsNone(site.login_url)

		# The Running event carries the minted handoff — it lands on the mirror.
		self._push(
			"site.status_changed",
			{"name": fqdn, "team": self.team.name, "subdomain": "handoff",
			 "status": "Running", "url": f"https://{fqdn}",
			 "login_url": f"https://{fqdn}/app?sid=xyz",
			 "login_url_expires_at": "2026-06-19 10:00:00"},
			"2026-06-18 10:05:00",
		)
		site.reload()
		self.assertEqual(site.url, f"https://{fqdn}")
		self.assertEqual(site.login_url, f"https://{fqdn}/app?sid=xyz")
		self.assertEqual(str(site.login_url_expires_at), "2026-06-19 10:00:00")

		# Write-once: a later status-only event without a login_url must not blank it.
		self._push(
			"site.status_changed",
			{"name": fqdn, "team": self.team.name, "subdomain": "handoff", "status": "Running"},
			"2026-06-18 10:10:00",
		)
		site.reload()
		self.assertEqual(site.login_url, f"https://{fqdn}/app?sid=xyz")

	def test_get_site_returns_stored_login_url_when_fresh(self):
		# A Running site with a not-yet-expired login URL: get_site returns it verbatim,
		# no regenerate round-trip to Atlas.
		from central.api import sites

		fqdn = "fresh.blr1.frappe.dev"
		self._push(
			"site.status_changed",
			{"name": fqdn, "team": self.team.name, "subdomain": "fresh",
			 "status": "Running", "url": f"https://{fqdn}",
			 "login_url": f"https://{fqdn}/app?sid=fresh",
			 "login_url_expires_at": "2099-01-01 00:00:00"},
			"2026-06-18 10:05:00",
		)
		frappe.set_user(self.owner)
		try:
			with patch(
				"central.integrations.atlas.AtlasClient.regenerate_site_login"
			) as regen:
				got = sites.get_site(fqdn)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(got["login_url"], f"https://{fqdn}/app?sid=fresh")
		regen.assert_not_called()

	def test_get_site_regenerates_expired_login_url(self):
		# A Running site whose stored login URL has expired: get_site re-mints it via
		# Atlas, re-mirrors, and returns the fresh URL.
		from central.api import sites

		fqdn = "stale.blr1.frappe.dev"
		self._push(
			"site.status_changed",
			{"name": fqdn, "team": self.team.name, "subdomain": "stale",
			 "status": "Running", "url": f"https://{fqdn}",
			 "login_url": f"https://{fqdn}/app?sid=stale",
			 "login_url_expires_at": "2000-01-01 00:00:00"},
			"2026-06-18 10:05:00",
		)
		fresh = {
			"name": fqdn, "team": self.team.name, "subdomain": "stale",
			"status": "Running", "url": f"https://{fqdn}",
			"login_url": f"https://{fqdn}/app?sid=fresh",
			"login_url_expires_at": "2099-01-01 00:00:00",
		}
		frappe.set_user(self.owner)
		try:
			with patch(
				"central.integrations.atlas.AtlasClient.regenerate_site_login", return_value=fresh
			) as regen:
				got = sites.get_site(fqdn)
		finally:
			frappe.set_user("Administrator")
		regen.assert_called_once_with(fqdn)
		self.assertEqual(got["login_url"], f"https://{fqdn}/app?sid=fresh")

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

	# --- power gate while resizing --------------------------------------------

	def _stopped_asset(self, resource_id, **extra):
		self._push("vm.created", {"name": resource_id, "team": self.team.name, "status": "Stopped"}, "2026-07-02 10:00:00")
		if extra:
			frappe.db.set_value("Asset", resource_id, extra)
		return resource_id

	def test_start_blocked_while_resizing(self):
		asset = self._stopped_asset("vm-resizing", resize_in_progress=1)
		frappe.set_user(self.owner)
		with self.assertRaisesRegex(frappe.ValidationError, "resizing"):
			start_server(team=self.team.name, resource_id=asset)

	def test_start_allowed_once_resize_clears(self):
		asset = self._stopped_asset("vm-idle", resize_in_progress=0)
		frappe.set_user(self.owner)
		with patch("central.integrations.atlas.AtlasClient.vm_action", return_value="task-1") as vm_action:
			start_server(team=self.team.name, resource_id=asset)
		vm_action.assert_called_once_with(asset, "start")
