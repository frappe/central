from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from central.errors import AtlasRequestUncertain, AtlasResourceGone
from central.infrastructure import runway
from central.integrations import runway as regional
from central.permissions import runner_lease_has_permission, runner_lease_query_conditions


class TestRunway(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.team = frappe.get_doc(
			{"doctype": "Team", "team_name": f"Runway test {uuid4()}", "owner_user": "Administrator"}
		).insert()
		self.region = frappe.get_doc(
			{
				"doctype": "Region",
				"region": f"test-{uuid4().hex[:12]}",
				"atlas_region_id": str(int(uuid4().hex[:4], 16)),
				"base_url": "https://atlas.example.test",
				"status": "Active",
			}
		).insert()
		from cryptography.hazmat.primitives import serialization
		from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

		key = (
			Ed25519PrivateKey.generate()
			.public_key()
			.public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
			.decode()
		)
		self.pool = frappe.get_doc(
			{
				"doctype": "Runner Pool",
				"title": "Runway integration test",
				"team": self.team.name,
				"region": self.region.name,
				"controller_user": "Administrator",
				"repository_url": "https://github.com/example/ci",
				"scale_set_id": 1,
				"scale_set_name": "runway-1vcpu-2gb",
				"image_id": "test-image",
				"status": "Active",
				"max_concurrency": 1,
				"cpu_millicores": 1000,
				"memory_mib": 2048,
				"disk_mib": 4096,
				"max_job_seconds": 600,
				"ssh_public_key": key,
			}
		).insert()
		self.owner = str(uuid4())
		self.fence = runway.claim_pool(self.pool.name, self.owner)["fence"]
		frappe.db.commit()
		self.addCleanup(self.cleanup_records)

	def cleanup_records(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		# Tests own disposable fixtures, including immutable lease audit rows.
		frappe.db.delete("Runner Lease", {"pool": self.pool.name})
		frappe.db.delete("Runner Pool", {"name": self.pool.name})
		frappe.db.delete("Region", {"name": self.region.name})
		frappe.db.delete("Team Member", {"parent": self.team.name})
		frappe.db.delete("Team", {"name": self.team.name})
		frappe.db.commit()

	def reserve(self):
		return runway.reserve_lease(self.pool.name, self.owner, self.fence, str(uuid4()))

	def test_a_pool_serves_the_repository_it_declares(self) -> None:
		"""The pool's own repository URL is what a job is checked against."""
		pool = SimpleNamespace(
			name="test-pool", repository_url="https://github.com/BreadGenie/frappe"
		)
		self.assertEqual(runway.pool_repository(pool), "BreadGenie/frappe")
		# Checked case-insensitively: GitHub and an operator may capitalise differently.
		runway.ensure_image_serves(pool, "breadgenie/frappe")
		runway.ensure_image_serves(pool, "BreadGenie/frappe")

	def test_a_pool_refuses_a_repository_it_does_not_serve(self) -> None:
		"""Refused before a guest exists, where refusing is still free."""
		pool = SimpleNamespace(
			name="test-pool", repository_url="https://github.com/BreadGenie/frappe"
		)
		with self.assertRaises(frappe.PermissionError) as raised:
			runway.ensure_image_serves(pool, "someone-elses/repo")
		self.assertIn("cannot serve", str(raised.exception))

	def test_an_empty_repository_is_not_a_decision(self) -> None:
		"""A job that names no repository passes through; the pairing needs both sides."""
		pool = SimpleNamespace(
			name="test-pool", repository_url="https://github.com/BreadGenie/frappe"
		)
		runway.ensure_image_serves(pool, "")
		runway.ensure_image_serves(pool, None)

	def test_the_lease_snapshot_reports_the_shape_a_job_was_given(self) -> None:
		"""The resolved shape is recorded so cost can be explained without the label."""
		from central.infrastructure.runway import lease_snapshot
		lease = frappe._dict(
			name="lease-shape", pool="pool", phase="running", repository="BreadGenie/frappe",
			request_labels="runway-4vcpu-8gb", resolved_cpu_millicores=4000,
			resolved_memory_mib=8192, resolved_disk_mib=14336, runner_name="r",
		)
		snap = lease_snapshot(lease)
		self.assertEqual(snap["resolved_cpu_millicores"], 4000)
		self.assertEqual(snap["resolved_memory_mib"], 8192)
		self.assertEqual(snap["resolved_disk_mib"], 14336)

	def test_a_shape_label_for_this_pool_is_accepted(self) -> None:
		"""A pool is one machine class, and the label that names it is accepted."""
		pool = SimpleNamespace(cpu_millicores=4000, memory_mib=8192, disk_mib=14336)
		self.assertEqual(
			runway.resolve_shape("self-hosted\nrunway-4vcpu-8gb", pool), (4000, 8192, 14336)
		)
		# The first shape label decides; the disk is always the pool's, because no label names one.
		self.assertEqual(
			runway.resolve_shape("runway-4vcpu-8gb\nrunway-2vcpu-4gb", pool), (4000, 8192, 14336)
		)

	def test_a_label_that_names_no_shape_keeps_the_pool(self) -> None:
		"""A pool created before labels keeps booting exactly what it always did."""
		pool = SimpleNamespace(cpu_millicores=3000, memory_mib=6144, disk_mib=14336)
		for labels in ("self-hosted", "runway-dogfood", "runway", "runway-huge", "", None, "gpu", "linux"):
			with self.subTest(labels=labels):
				self.assertEqual(runway.resolve_shape(labels, pool), (3000, 6144, 14336))

	def test_a_shape_label_the_pool_does_not_serve_is_refused(self) -> None:
		"""A job never runs on a machine its own label did not ask for."""
		pool = SimpleNamespace(cpu_millicores=3000, memory_mib=6144, disk_mib=14336)
		for label in ("runway-4vcpu-8gb", "runway-2vcpu-4gb", "runway-4vcpu-9gb"):
			with self.subTest(label=label):
				with self.assertRaises(frappe.ValidationError) as caught:
					runway.resolve_shape(label, pool)
				self.assertIn("this pool serves 3 vCPU and 6 GiB", str(caught.exception))

	def test_a_malformed_shape_label_is_refused_with_the_form(self) -> None:
		"""A typo names a shape badly, which is a mistake worth reporting."""
		pool = SimpleNamespace(cpu_millicores=3000, memory_mib=6144, disk_mib=14336)
		for label in ("runway-4vcup-8gb", "runway-8gb-4vcpu", "runway-4vcpu", "runway-64vcpu"):
			with self.subTest(label=label):
				with self.assertRaises(frappe.ValidationError) as caught:
					runway.resolve_shape(label, pool)
				self.assertIn("not a runner shape", str(caught.exception))

	def test_a_scale_set_name_may_name_no_shape(self) -> None:
		"""A legacy name like runway-dogfood states nothing to check against the pool."""
		for name in ("runway-dogfood", "runway-frappe", "runway-1vcpu-2gb-x"):
			with self.subTest(name=name):
				self.pool.scale_set_name = name
				self.pool.validate()

	def test_a_scale_set_name_that_states_this_pool_is_accepted(self) -> None:
		"""The shape in the name is the shape the pool builds."""
		self.pool.scale_set_name = "runway-1vcpu-2gb"
		self.pool.validate()

	def test_a_scale_set_name_contradicting_the_pool_is_refused(self) -> None:
		"""Otherwise a workflow asking for 8 GiB is admitted by the name and handed 2."""
		self.pool.scale_set_name = "runway-4vcpu-8gb"
		with self.assertRaises(frappe.ValidationError) as caught:
			self.pool.validate()
		self.assertIn(
			"states 4 vCPU and 8 GiB, but this pool serves 1 vCPU and 2 GiB", str(caught.exception)
		)

	def test_a_scale_set_name_that_is_not_routable_is_refused(self) -> None:
		"""A name that could never be a scale set name would leave no way to reach this pool."""
		for name in ("dogfood", "Runway-1vcpu-2gb", "runway_1vcpu_2gb", "runway-1VCPU-2GB", "", "runway"):
			with self.subTest(name=name):
				self.pool.scale_set_name = name
				with self.assertRaises(frappe.ValidationError):
					self.pool.validate()

	def test_the_shape_label_matches_the_scale_set_name(self) -> None:
		"""The label a pool hands out is the name that routes to it."""
		self.assertEqual(runway.scale_label_for_shape(4000, 8192), "runway-4vcpu-8gb")
		self.assertEqual(runway.scale_label_for_shape(1000, 2048), "runway-1vcpu-2gb")
		self.assertEqual(
			runway.shape_from_scale_set_name("runway-4vcpu-8gb"), (4000, 8192)
		)
		self.assertIsNone(runway.shape_from_scale_set_name("runway-dogfood"))

	def test_the_largest_permitted_shape_is_accepted(self) -> None:
		"""4 vCPU and 9 GiB is a shape a pool may declare, and name, once hardware exists."""
		self.pool.scale_set_name = "runway-4vcpu-9gb"
		self.pool.cpu_millicores = 4000
		self.pool.memory_mib = 9216
		self.pool.validate()

	def test_a_shape_beyond_the_policy_is_refused(self) -> None:
		"""The limit is policy, so a pool above it is refused before any host is asked."""
		self.pool.scale_set_name = "runway-16vcpu-64gb"
		self.pool.cpu_millicores = 16000
		self.pool.memory_mib = 65536
		with self.assertRaises(frappe.ValidationError) as caught:
			self.pool.validate()
		self.assertIn("outside pilot limits", str(caught.exception))

	def test_runner_identity_survives_schema_reload(self):
		lease = self.reserve()
		runner_id = 2**40 + 219
		frappe.db.set_value("Runner Lease", lease["id"], "phase", "jit_pending")
		result = runway.update_lease(
			self.pool.name, self.owner, self.fence, lease["id"], "jit_ready", runner_id=runner_id
		)
		self.assertEqual(result["runner_id"], runner_id)
		frappe.db.commit()

		frappe.reload_doc("infrastructure", "doctype", "runner_lease", force=True)
		stored = frappe.get_doc("Runner Lease", lease["id"])
		self.assertEqual(runway.lease_snapshot(stored)["runner_id"], runner_id)

	def test_duplicate_reservation_cannot_bypass_capacity(self):
		lease = self.reserve()
		self.assertEqual(
			runway.reserve_lease(self.pool.name, self.owner, self.fence, lease["id"])["id"], lease["id"]
		)
		with self.assertRaises(frappe.ValidationError):
			self.reserve()
		self.assertEqual(len(runway.active_leases(pool=self.pool.name)), 1)

	def test_concurrent_reservations_share_one_capacity_slot(self):
		site, sites_path = frappe.local.site, frappe.local.sites_path
		pool, owner, fence = self.pool.name, self.owner, self.fence
		barrier = Barrier(2)
		frappe.db.commit()

		def reserve_concurrently():
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			frappe.set_user("Administrator")
			try:
				barrier.wait(timeout=10)
				runway.reserve_lease(pool, owner, fence, str(uuid4()))
				frappe.db.commit()
				return "reserved"
			except frappe.ValidationError:
				frappe.db.rollback()
				return "full"
			finally:
				frappe.destroy()

		with ThreadPoolExecutor(max_workers=2) as executor:
			results = list(executor.map(lambda _: reserve_concurrently(), range(2)))
		self.assertCountEqual(results, ["reserved", "full"])

	def test_pool_identity_stays_frozen_until_github_cleanup(self):
		lease = self.reserve()
		frappe.db.set_value("Runner Lease", lease["id"], {"phase": "deleted", "jit_state": "ready"})
		self.pool.reload()
		self.pool.repository_url = "https://github.com/other/repository"
		with self.assertRaises(frappe.ValidationError):
			self.pool.save()

	def test_reclaim_fences_old_controller(self):
		new = runway.claim_pool(self.pool.name, self.owner)
		self.assertGreater(new["fence"], self.fence)
		with self.assertRaises(frappe.PermissionError):
			self.reserve()

	def test_controller_requires_pool_assignment_and_capabilities(self):
		with (
			patch.object(runway, "user_has_operator_bypass", return_value=False),
			patch.object(runway, "can", return_value=True),
		):
			pool = SimpleNamespace(controller_user="someone-else", team=self.team.name)
			with self.assertRaises(frappe.PermissionError):
				runway.authorize(pool)
		with (
			patch.object(runway, "user_has_operator_bypass", return_value=False),
			patch.object(runway, "can", return_value=False),
		):
			with self.assertRaises(frappe.PermissionError):
				runway.authorize(self.pool)

	def test_lease_access_denies_cross_team_and_direct_writes(self):
		with (
			patch("central.permissions.user_has_operator_bypass", return_value=False),
			patch(
				"central.permissions.can", side_effect=lambda user, team, capability: team == self.team.name
			),
			patch("central.permissions.get_user_team_names_with_capability", return_value=[]),
		):
			self.assertTrue(
				runner_lease_has_permission(SimpleNamespace(team=self.team.name), "reader", "read")
			)
			self.assertFalse(runner_lease_has_permission(SimpleNamespace(team="other"), "reader", "read"))
			self.assertFalse(
				runner_lease_has_permission(SimpleNamespace(team=self.team.name), "reader", "write")
			)
			self.assertEqual(runner_lease_query_conditions("outsider"), "1 = 0")
		lease = self.reserve()
		with self.assertRaises(frappe.PermissionError):
			runway.scoped_lease(SimpleNamespace(name="other-pool", team=self.team.name), lease["id"])

	def test_uncertain_create_is_not_repeated_and_can_be_discovered(self):
		lease = self.reserve()
		client = Mock()
		client.create_vm.side_effect = AtlasRequestUncertain("lost reply")
		client.list_vms.return_value = []
		with patch.object(regional, "client_for_pool", return_value=client):
			first = regional.ensure_vm(self.pool.name, self.owner, self.fence, lease["id"])
			self.assertEqual(first["phase"], "uncertain")
			regional.ensure_vm(self.pool.name, self.owner, self.fence, lease["id"])
			client.create_vm.assert_called_once()
			client.list_vms.return_value = [
				{"id": "vm-42", "tags": {"runway_pool": self.pool.name, "runway_lease": lease["id"]}}
			]
			client.get_vm.return_value = {"current_state": "running", "network": {"mesh_ipv6": "fdaa::42"}}
			found = regional.ensure_vm(self.pool.name, self.owner, self.fence, lease["id"])
			self.assertEqual(found["vm_id"], "vm-42")
			self.assertEqual(found["phase"], "vm_ready")
			client.create_vm.assert_called_once()

	def test_uncertain_create_preserves_concurrent_cleanup_intent(self):
		lease = self.reserve()
		client = Mock()

		def concurrent_cleanup(_payload):
			frappe.db.set_value("Runner Lease", lease["id"], "phase", "deleting")
			frappe.db.commit()
			return {}

		client.create_vm.side_effect = concurrent_cleanup
		client.list_vms.return_value = []
		with patch.object(regional, "client_for_pool", return_value=client):
			result = regional.ensure_vm(self.pool.name, self.owner, self.fence, lease["id"])
		self.assertEqual(result["phase"], "deleting")

	def test_expired_vm_requires_scoped_absence_and_github_cleanup(self):
		lease = self.reserve()
		frappe.db.set_value(
			"Runner Lease",
			lease["id"],
			{
				"vm_id": "vm-42",
				"phase": "running",
				"jit_state": "ready",
				"deadline": add_to_date(now_datetime(), seconds=-1),
			},
		)
		frappe.db.commit()
		client = Mock()
		client.get_vm.return_value = {"current_state": "running", "network": {}}
		with patch.object(regional, "client_for_pool", return_value=client):
			regional.reconcile_lease(self.pool, lease["id"])
			self.assertEqual(frappe.db.get_value("Runner Lease", lease["id"], "phase"), "deleting")
			client.vm_action.assert_called_once_with("vm-42", "terminate")
			client.get_vm.side_effect = AtlasResourceGone("scoped 404")
			regional.reconcile_lease(self.pool, lease["id"])
			self.assertEqual(frappe.db.get_value("Runner Lease", lease["id"], "phase"), "deleted")
			self.assertEqual(len(runway.active_leases(pool=self.pool.name)), 1)
			runway.update_lease(self.pool.name, self.owner, self.fence, lease["id"], "runner_removed")
			self.assertEqual(runway.active_leases(pool=self.pool.name), [])

	def test_delete_reply_does_not_overwrite_concurrent_runner_cleanup(self):
		lease = self.reserve()
		frappe.db.set_value(
			"Runner Lease", lease["id"], {"phase": "deleting", "vm_id": "vm-42", "jit_state": "ready"}
		)
		client = Mock()
		client.get_vm.return_value = {"current_state": "running", "network": {}}

		def report_github_cleanup(*_):
			frappe.db.set_value("Runner Lease", lease["id"], "jit_state", "removed")
			frappe.db.commit()

		client.vm_action.side_effect = report_github_cleanup
		with patch.object(regional, "client_for_pool", return_value=client):
			regional.reconcile_lease(self.pool, lease["id"])
		self.assertEqual(frappe.db.get_value("Runner Lease", lease["id"], "jit_state"), "removed")

	def test_retirement_reason_survives_runner_removed_and_cleanup(self):
		lease = self.reserve()
		frappe.db.set_value("Runner Lease", lease["id"], {"vm_id": "vm-42", "phase": "running"})
		frappe.db.commit()
		reason = "JIT registration outcome uncertain; registration requires cleanup"
		retirement = runway.update_lease(
			self.pool.name, self.owner, self.fence, lease["id"], "failed", error=reason
		)
		self.assertEqual(retirement["phase"], "deleting")
		self.assertEqual(retirement["last_error"], reason)
		client = Mock()
		client.get_vm.return_value = {"current_state": "running", "network": {}}
		with patch.object(regional, "client_for_pool", return_value=client):
			regional.reconcile_lease(self.pool, lease["id"])
			client.get_vm.side_effect = AtlasResourceGone("scoped 404")
			regional.reconcile_lease(self.pool, lease["id"])
		self.assertEqual(frappe.db.get_value("Runner Lease", lease["id"], "phase"), "deleted")
		self.assertEqual(frappe.db.get_value("Runner Lease", lease["id"], "last_error"), reason)
		removed = runway.update_lease(self.pool.name, self.owner, self.fence, lease["id"], "runner_removed")
		self.assertEqual(removed["jit_state"], "removed")
		self.assertEqual(removed["last_error"], reason)

	def test_completion_diagnostic_failure_survives_runner_removed(self):
		lease = self.reserve()
		reason = "Job log upload failed; diagnostics are incomplete"
		completed = runway.update_lease(
			self.pool.name,
			self.owner,
			self.fence,
			lease["id"],
			"completed",
			result="success",
			error=reason,
		)
		self.assertEqual(completed["last_error"], reason)
		removed = runway.update_lease(self.pool.name, self.owner, self.fence, lease["id"], "runner_removed")
		self.assertEqual(removed["jit_state"], "removed")
		self.assertEqual(removed["last_error"], reason)
		# A later error is new evidence, so it replaces the stored diagnostic failure.
		replaced = runway.update_lease(
			self.pool.name,
			self.owner,
			self.fence,
			lease["id"],
			"failed",
			error="Runner cleanup verification timed out",
		)
		self.assertEqual(replaced["last_error"], "Runner cleanup verification timed out")

	def test_reaper_locks_pool_before_lease_like_the_rpc_path(self):
		"""The scheduler reaper and the controller RPC must take row locks in one order.

		The RPC path locks the pool, then the lease. If the reaper locks the lease
		first it holds that lock across Atlas calls, and the two transactions
		deadlock, which Frappe reports to the controller as HTTP 508.
		"""
		lease = self.reserve()
		order = []

		original_get_doc = frappe.get_doc

		def tracked_get_doc(doctype, name=None, *args, **kwargs):
			if doctype == "Runner Pool" and kwargs.get("for_update"):
				order.append("pool")
			elif doctype == "Runner Lease" and kwargs.get("for_update"):
				order.append("lease")
			return original_get_doc(doctype, name, *args, **kwargs)

		with patch.object(regional.frappe, "get_doc", side_effect=tracked_get_doc):
			client = Mock()
			client.list_vms.return_value = []
			with patch.object(regional, "client_for_pool", return_value=client):
				regional.reconcile_lease(self.pool, lease["id"])

		self.assertEqual(order[:2], ["pool", "lease"], f"reaper locked {order}, expected pool before lease")

	def test_reaper_and_rpc_do_not_deadlock_under_concurrency(self):
		"""A concurrent reaper sweep and controller RPC must both complete.

		Inconsistent lock order between these two paths is the reported cause of
		HTTP 508 renewals that stop the controller while the pool stays active.
		The reaper runs the real sweep, including its pool and lease pre-reads,
		because those reads open the transaction the locks are taken in.
		"""
		lease = self.reserve()
		frappe.db.set_value("Runner Lease", lease["id"], {"phase": "deleting", "vm_state": "running"})
		site, sites_path = frappe.local.site, frappe.local.sites_path
		pool, owner, fence = self.pool.name, self.owner, self.fence
		barrier = Barrier(2)
		failures = []
		frappe.db.commit()

		def reap():
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			frappe.set_user("Administrator")
			try:
				barrier.wait(timeout=10)
				client = Mock()
				client.get_vm.return_value = {"current_state": "running"}
				client.list_vms.return_value = []
				with patch.object(regional, "client_for_pool", return_value=client):
					# Run the real sweep, including its pool and lease pre-reads,
					# because those reads open the transaction the locks are taken in.
					# This test owns the only pool on the site, so sweep touches nothing else.
					regional.sweep()
			except Exception as error:  # noqa: BLE001 - the assertion reports the type
				failures.append(f"reap: {type(error).__name__}: {error}")
			finally:
				frappe.db.rollback()
				frappe.destroy()

		def controller():
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			frappe.set_user("Administrator")
			try:
				barrier.wait(timeout=10)
				regional.request_delete(pool, owner, fence, lease["id"])
			except Exception as error:  # noqa: BLE001 - the assertion reports the type
				failures.append(f"rpc: {type(error).__name__}: {error}")
			finally:
				frappe.db.rollback()
				frappe.destroy()

		with ThreadPoolExecutor(max_workers=2) as executor:
			for future in [executor.submit(reap), executor.submit(controller)]:
				future.result()

		self.assertEqual(failures, [], f"concurrent reaper and RPC failed with {failures}")

	def test_unknown_create_cannot_be_declared_deleted(self):
		lease = self.reserve()
		frappe.db.set_value(
			"Runner Lease", lease["id"], {"phase": "deleting", "create_dispatched_at": now_datetime()}
		)
		client = Mock()
		client.list_vms.return_value = []
		with patch.object(regional, "client_for_pool", return_value=client):
			regional.reconcile_lease(self.pool, lease["id"])
		self.assertEqual(frappe.db.get_value("Runner Lease", lease["id"], "phase"), "deleting")
		client.create_vm.assert_not_called()

	def test_orphan_cleanup_requires_owned_tags(self):
		client = Mock()
		client.list_vms.return_value = [
			{
				"id": "orphan",
				"tags": {
					"runway_pool": self.pool.name,
					"runway_lease": str(uuid4()),
					"team": self.team.name,
					"role": "ci",
				},
			},
			{"id": "unrelated", "tags": {"runway_pool": self.pool.name}},
		]
		with patch.object(regional, "client_for_pool", return_value=client):
			regional.remove_orphans(self.pool)
		client.vm_action.assert_called_once_with("orphan", "terminate")
