from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from central.api import snapshots as api
from central.billing.revenue.invoicing.lines import team_line_items
from central.billing.settings import ensure_snapshot_settings
from central.errors import AtlasRejected, AtlasRequestUncertain, AtlasResourceGone
from central.infrastructure.doctype.image_offering.image_offering import ensure_default_offerings
from central.infrastructure.doctype.vm_snapshot import vm_snapshot
from central.infrastructure.doctype.vm_snapshot.vm_snapshot import VMSnapshot
from central.integrations.atlas import AtlasClient
from central.integrations.images import snapshot_image, snapshot_source
from central.integrations.servers import process_command
from central.resource_actions import submit_command
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance


def image(status: str = "available", size_mib: int = 20480, **values) -> dict:
	return {"id": "img-1", "status": status, "rootfs_size_mib": size_mib, "transfer_error": None, **values}


class SnapshotTestCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=6)
		self.region = ensure_atlas_instance(f"snap-{self.suffix}")
		self.owner = ensure_user("snapshot.owner@example.test")
		self.viewer = ensure_user("snapshot.viewer@example.test")
		self.team = self._team("Snapshots", {self.viewer: "Viewer"})
		self.server = self._server("a", self.team)
		self.enqueue = self.enterContext(patch("frappe.enqueue_doc"))
		self.enterContext(patch.object(frappe.db, "commit"))
		self.enterContext(patch.object(frappe.db, "rollback"))

	def tearDown(self):
		frappe.set_user("Administrator")

	def _team(self, label: str, members: dict[str, str]) -> str:
		rows = [{"user": self.owner, "role": "Owner", "status": "Active"}]
		rows += [{"user": user, "role": role, "status": "Active"} for user, role in members.items()]
		return (
			frappe.get_doc(
				{
					"doctype": "Team",
					"team_name": f"{label} {self.suffix}",
					"owner_user": self.owner,
					"members": rows,
				}
			)
			.insert()
			.name
		)

	def _server(self, label: str, team: str, status: str = "Running"):
		return frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": f"vm-snap-{label}-{self.suffix}",
				"team": team,
				"cluster": self.region,
				"status": status,
				"atlas_vm_id": f"atlas-{label}-{self.suffix}",
			}
		).insert(ignore_permissions=True)

	def _snapshot(self, snapshot_type: str = "Manual", server=None) -> VMSnapshot:
		server = server or self.server
		return frappe.get_doc(
			{
				"doctype": "VM Snapshot",
				"title": "Test snapshot",
				"team": server.team,
				"server": server.name,
				"snapshot_type": snapshot_type,
			}
		).insert(ignore_permissions=True)

	def _available(self, snapshot_type: str = "Manual", hours_old: int = 0) -> VMSnapshot:
		snapshot = self._snapshot(snapshot_type)
		snapshot.db_set(
			{"atlas_image_id": "img-1", "creation": add_to_date(now_datetime(), hours=-hours_old)}
		)
		with patch.object(AtlasClient, "get_machine_image", return_value=image()):
			snapshot.sync()
		return snapshot

	def _three_snapshots(self) -> list[VMSnapshot]:
		"""Three available snapshots of one server, oldest first."""
		return [self._available(hours_old=hours) for hours in (3, 2, 1)]


class TestSnapshotLifecycle(SnapshotTestCase):
	def test_only_a_daily_snapshot_is_deleted_on_its_own(self):
		automatic = self._snapshot("Automatic")
		manual = self._snapshot("Manual", self._server("b", self.team))
		terminate = self._snapshot("Terminate", self._server("c", self.team))

		self.assertGreater(automatic.expires_at, add_to_date(now_datetime(), hours=47))
		self.assertIsNone(manual.expires_at)
		self.assertIsNone(terminate.expires_at)
		self.assertEqual((automatic.region, automatic.status), (self.region, "Pending"))

	def test_a_server_of_another_team_is_refused(self):
		other = self._server("other", self._team("Other", {}))

		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "VM Snapshot",
					"title": "x",
					"team": self.team,
					"server": other.name,
					"snapshot_type": "Manual",
				}
			).insert(ignore_permissions=True)

	def test_one_snapshot_runs_per_server(self):
		self._snapshot()

		with self.assertRaises(frappe.ValidationError):
			self._snapshot()

	def test_send_records_the_image_or_the_reason(self):
		sent = self._snapshot()
		refused = self._snapshot("Manual", self._server("b", self.team))
		lost = self._snapshot("Manual", self._server("c", self.team))

		with patch.object(AtlasClient, "create_snapshot", return_value={"id": "img-9"}):
			sent.send_to_region()
		with patch.object(AtlasClient, "create_snapshot", side_effect=AtlasRejected("host is full")):
			refused.send_to_region()
		with patch.object(AtlasClient, "create_snapshot", side_effect=AtlasRequestUncertain("no reply")):
			lost.send_to_region()

		self.assertEqual(frappe.db.get_value("VM Snapshot", sent.name, "atlas_image_id"), "img-9")
		self.assertEqual(refused.status, "Failed")
		self.assertEqual(refused.error_detail, "The region could not start this snapshot.")
		self.assertIn("host is full", frappe.db.get_value("Error Log", refused.error_log, "error"))
		self.assertEqual(
			frappe.db.get_value("Error Log", refused.error_log, ["reference_doctype", "reference_name"]),
			("VM Snapshot", refused.name),
		)
		self.assertEqual(frappe.db.get_value("VM Snapshot", lost.name, "status"), "Pending")

	def test_sync_finds_a_lost_reply_by_its_tag(self):
		snapshot = self._snapshot()

		with patch.object(AtlasClient, "find_snapshot_image", return_value=image()) as find:
			snapshot.sync()

		find.assert_called_once_with(snapshot.name)
		self.assertEqual(
			(snapshot.status, snapshot.atlas_image_id, snapshot.size_mib), ("Available", "img-1", 20480)
		)

	def test_sync_records_a_failed_or_missing_image(self):
		failed = self._snapshot()
		failed.db_set("atlas_image_id", "img-1")
		gone = self._snapshot("Manual", self._server("b", self.team))
		gone.db_set("atlas_image_id", "img-2")

		with patch.object(
			AtlasClient, "get_machine_image", return_value=image("failed", transfer_error="disk read")
		):
			failed.sync()
		with patch.object(AtlasClient, "get_machine_image", side_effect=AtlasResourceGone("gone")):
			gone.sync()

		self.assertEqual(
			(failed.status, failed.error_detail),
			("Failed", "The region could not finish this snapshot."),
		)
		self.assertIn("disk read", frappe.db.get_value("Error Log", failed.error_log, "error"))
		self.assertEqual(gone.status, "Failed")

	def test_failure_queues_one_snapshot_notification(self):
		snapshot = self._snapshot()
		snapshot.db_set("atlas_image_id", "img-1")

		with (
			patch.object(AtlasClient, "get_machine_image", return_value=image("failed")),
			patch("central.notification.engine.queue_event") as queue_event,
		):
			snapshot.sync()

		queue_event.assert_called_once_with(
			self.team,
			"snapshot_failure",
			message="The region could not finish this snapshot.",
			reference_doctype="VM Snapshot",
			reference_name=snapshot.name,
		)

	def test_the_two_newest_snapshots_of_a_server_are_free(self):
		oldest, middle, newest = self._three_snapshots()

		for snapshot in (oldest, middle, newest):
			snapshot.reload()
		self.assertEqual([s.is_free for s in (oldest, middle, newest)], [0, 1, 1])
		self.assertIsNone(middle.subscription)
		self.assertIsNone(newest.subscription)

		subscription = frappe.get_doc("Subscription", oldest.subscription)
		self.assertEqual(subscription.vm_snapshot, oldest.name)
		self.assertEqual(
			[(row.resource_type, row.quantity) for row in subscription.includes], [("Snapshot", 20)]
		)
		rate = frappe.db.get_value("Subscription Change", {"subscription": subscription.name}, "locked_rate")
		self.assertEqual(rate, 20 * 6.5)

	def test_deleting_a_newer_snapshot_makes_an_older_one_free(self):
		oldest, _, newest = self._three_snapshots()
		oldest.reload()
		billed = oldest.subscription

		with patch.object(AtlasClient, "delete_image") as delete:
			frappe.get_doc("VM Snapshot", newest.name).delete_from_region()

		delete.assert_called_once_with("img-1")
		oldest.reload()
		self.assertEqual(frappe.db.get_value("VM Snapshot", newest.name, "status"), "Deleted")
		self.assertEqual((oldest.is_free, oldest.subscription), (1, None))
		self.assertFalse(frappe.db.get_value("Subscription", billed, "enabled"))

	def test_a_kept_daily_snapshot_is_not_deleted_on_its_own(self):
		snapshot = self._available("Automatic")

		snapshot.keep()

		self.assertIsNone(snapshot.expires_at)
		self.assertEqual(frappe.db.get_value("VM Snapshot", snapshot.name, "is_free"), 1)

	def test_a_pending_snapshot_cannot_be_deleted(self):
		with self.assertRaises(frappe.ValidationError):
			self._snapshot().delete_from_region()


class TestSnapshotSchedules(SnapshotTestCase):
	def test_automatic_snapshots_follow_the_region_and_server_settings(self):
		skipped = self._server("skip", self.team)
		skipped.db_set("skip_automatic_snapshot", 1)
		frappe.db.set_value("Region", self.region, "automatic_snapshots", 0)

		vm_snapshot.take_automatic_snapshots()
		self.assertFalse(frappe.db.exists("VM Snapshot", {"server": self.server.name}))

		frappe.db.set_value("Region", self.region, "automatic_snapshots", 1)
		vm_snapshot.take_automatic_snapshots()
		vm_snapshot.take_automatic_snapshots()

		self.assertEqual(
			frappe.db.count("VM Snapshot", {"server": self.server.name, "snapshot_type": "Automatic"}), 1
		)
		self.assertFalse(frappe.db.exists("VM Snapshot", {"server": skipped.name}))

	def test_only_expired_daily_snapshots_are_deleted(self):
		expired = self._available("Automatic")
		expired.db_set("expires_at", add_to_date(now_datetime(), hours=-1))
		kept = self._snapshot("Terminate", self._server("b", self.team))
		kept.db_set({"atlas_image_id": "img-2", "status": "Available", "size_mib": 10240})

		with patch.object(AtlasClient, "delete_image"):
			vm_snapshot.delete_expired_snapshots()

		self.assertEqual(frappe.db.get_value("VM Snapshot", expired.name, "status"), "Deleted")
		self.assertEqual(frappe.db.get_value("VM Snapshot", kept.name, "status"), "Available")

	def test_a_refused_delete_leaves_its_reason_on_the_record(self):
		expired = self._available("Automatic")
		expired.db_set("expires_at", add_to_date(now_datetime(), hours=-1))

		with patch.object(AtlasClient, "delete_image", side_effect=AtlasRejected("image in use")):
			vm_snapshot.delete_expired_snapshots()

		self.assertEqual(frappe.db.get_value("VM Snapshot", expired.name, "status"), "Available")
		self.assertEqual(
			frappe.db.get_value("VM Snapshot", expired.name, "error_detail"),
			"Central could not delete this expired snapshot.",
		)
		self.assertIn(
			"image in use",
			frappe.db.get_value(
				"Error Log",
				frappe.db.get_value("VM Snapshot", expired.name, "error_log"),
				"error",
			),
		)


class TestSnapshotSettingsSeed(IntegrationTestCase):
	def test_the_seed_fills_a_missing_setting_and_keeps_a_stored_one(self):
		frappe.db.set_single_value("Billing Settings", "free_snapshots_per_server", 0)
		frappe.db.delete(
			"Singles", {"doctype": "Billing Settings", "field": "daily_snapshot_retention_hours"}
		)

		ensure_snapshot_settings()

		self.assertEqual(frappe.db.get_single_value("Billing Settings", "free_snapshots_per_server"), 0)
		self.assertEqual(frappe.db.get_single_value("Billing Settings", "daily_snapshot_retention_hours"), 48)


class TestSnapshotAccess(SnapshotTestCase):
	def test_team_members_read_only_their_snapshots(self):
		own = self._snapshot()
		other = self._snapshot("Manual", self._server("other", self._team("Other", {})))

		frappe.set_user(self.viewer)
		names = {row["name"] for row in api.list_snapshots(self.team)["snapshots"]}

		self.assertIn(own.name, names)
		self.assertNotIn(other.name, names)
		self.assertFalse(frappe.has_permission("VM Snapshot", doc=other.name, user=self.viewer))

	def test_a_viewer_cannot_take_or_delete_a_snapshot(self):
		snapshot = self._available()

		frappe.set_user(self.viewer)
		with self.assertRaises(frappe.PermissionError):
			api.take_snapshot(self.team, self.server.name)
		with self.assertRaises(frappe.PermissionError):
			api.delete_snapshots(self.team, [snapshot.name])

	def test_delete_reports_each_failure_by_name(self):
		available = self._available()
		pending = self._snapshot("Manual", self._server("b", self.team))

		frappe.set_user(self.owner)
		with patch.object(AtlasClient, "delete_image"):
			result = api.delete_snapshots(self.team, [available.name, pending.name])

		self.assertEqual(result["deleted"], [available.name])
		self.assertIn(pending.name, result["failed"])

	def test_a_snapshot_of_another_team_cannot_be_named(self):
		other = self._snapshot("Manual", self._server("other", self._team("Other", {})))

		frappe.set_user(self.owner)
		with self.assertRaises(frappe.DoesNotExistError):
			api.keep_snapshot(self.team, other.name)


class TestTerminateWithSnapshot(SnapshotTestCase):
	def setUp(self):
		super().setUp()
		self.client = MagicMock()
		self.enterContext(patch("central.integrations.servers._client", return_value=self.client))
		self.enterContext(patch("central.integrations.servers._wait_for_power_state"))
		self.enterContext(patch("central.integrations.servers.observe_server", return_value="Terminated"))
		self.enterContext(patch("frappe.enqueue"))
		frappe.set_user(self.owner)
		status = submit_command("terminate", self.team, self.server.name, take_snapshot=True)
		frappe.set_user("Administrator")
		self.action = frappe.get_doc("Resource Action", status["action"])

	def test_the_server_is_destroyed_only_after_its_snapshot_is_available(self):
		process_command(self.action)
		self.action.reload()

		snapshot = frappe.get_doc("VM Snapshot", self.action.vm_snapshot)
		self.assertEqual((snapshot.snapshot_type, self.action.status), ("Terminate", "Queued"))
		self.client.vm_action.assert_not_called()

		snapshot.db_set("status", "Available")
		process_command(self.action)

		self.client.vm_action.assert_called_once_with(self.server.atlas_vm_id, "terminate")

	def test_a_failed_snapshot_keeps_the_server(self):
		process_command(self.action)
		self.action.reload()
		frappe.db.set_value("VM Snapshot", self.action.vm_snapshot, "status", "Failed")

		process_command(self.action)
		self.action.reload()

		self.assertEqual((self.action.status, self.action.error_code), ("Failed", "SNAPSHOT_FAILED"))
		self.client.vm_action.assert_not_called()

	def test_a_snapshot_needs_the_snapshot_capability(self):
		frappe.set_user(self.viewer)
		with self.assertRaises(frappe.PermissionError):
			submit_command("terminate", self.team, self.server.name, take_snapshot=True)


class TestSnapshotRestore(SnapshotTestCase):
	def setUp(self):
		super().setUp()
		ensure_default_offerings()
		self.server.db_set("image_offering", "ubuntu")
		self.snapshot = self._available()
		frappe.set_user(self.owner)

	def test_an_available_snapshot_restores_in_its_own_region(self):
		self.assertEqual(snapshot_source(self.team, self.snapshot.name), ("ubuntu", "img-1"))

		with self.assertRaises(frappe.ValidationError):
			snapshot_image(self.team, ensure_atlas_instance(f"elsewhere-{self.suffix}"), self.snapshot.name)

	def test_a_pilot_or_unfinished_snapshot_is_refused(self):
		self.snapshot.db_set("is_restorable", 0)
		with self.assertRaises(frappe.ValidationError):
			snapshot_source(self.team, self.snapshot.name)

		self.snapshot.db_set({"is_restorable": 1, "status": "Deleted"})
		with self.assertRaises(frappe.ValidationError):
			snapshot_source(self.team, self.snapshot.name)

	def test_a_viewer_cannot_restore(self):
		frappe.set_user(self.viewer)
		with self.assertRaises(frappe.PermissionError):
			snapshot_source(self.team, self.snapshot.name)


class TestSnapshotInvoicing(SnapshotTestCase):
	def test_a_billed_snapshot_is_an_invoice_line_in_its_region(self):
		self._three_snapshots()
		start = frappe.utils.get_first_day(frappe.utils.nowdate())
		end = frappe.utils.get_last_day(frappe.utils.nowdate())

		lines = [
			line
			for line in team_line_items(self.team, start, end)
			if line["plan"] == "Snapshot storage: 20 GB"
		]

		self.assertTrue(lines)
		self.assertEqual({(line["cluster"], line["rate"]) for line in lines}, {(self.region, 20 * 6.5)})
