from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.servers import registry, server_overview
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance

TARGET = {"vcpus": 8.0, "memory_megabytes": 16384, "disk_gigabytes": 80}
CURRENT_SHAPE = {"vcpus": 4.0, "memory_megabytes": 8192, "disk_gigabytes": 40}
RESIZE_PAYLOAD = {"shape": TARGET, "from_shape": CURRENT_SHAPE}
# A disk-only resize keeps the server running, so its worker never stops it.
DISK_ONLY_TARGET = {**CURRENT_SHAPE, "disk_gigabytes": 80}
DISK_ONLY_PAYLOAD = {"shape": DISK_ONLY_TARGET, "from_shape": CURRENT_SHAPE}


class TestResizeProgress(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		# A queued action enqueues its worker on insert; these tests read the record only.
		self.enterContext(patch("frappe.enqueue"))

		self.owner = ensure_user("resize.owner@example.test")
		self.viewer = ensure_user("resize.viewer@example.test")
		self.team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Resize progress",
				"owner_user": self.owner,
				"members": [
					{"user": self.owner, "role": "Owner", "status": "Active"},
					{"user": self.viewer, "role": "Viewer", "status": "Active"},
				],
			}
		).insert()
		self.addCleanup(self.team.delete, force=True)

		self.region = "blr-resize-progress"
		ensure_atlas_instance(self.region)

		self.server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": f"vm-resize-{frappe.generate_hash(length=8)}",
				"title": "Resize progress server",
				"team": self.team.name,
				"region": self.region,
				"status": "Running",
				"vcpus": CURRENT_SHAPE["vcpus"],
				"memory_megabytes": CURRENT_SHAPE["memory_megabytes"],
				"disk_gigabytes": CURRENT_SHAPE["disk_gigabytes"],
				"atlas_vm_id": f"vm-{frappe.generate_hash(length=16)}",
			}
		).insert()
		self.addCleanup(self.server.delete, force=True)

	def make_action(self, status: str = "Queued", **fields):
		action = frappe.get_doc(
			{
				"doctype": "Resource Action",
				"resource_type": "Server",
				"action": "resize",
				"team": self.team.name,
				"region": self.region,
				"server": self.server.name,
				"resource_id": self.server.name,
				"correlation_id": frappe.generate_hash(length=32),
				"status": status,
				"request_payload": RESIZE_PAYLOAD,
				**fields,
			}
		).insert()
		self.addCleanup(action.delete, force=True)

		return action

	def dispatch(self, status: str = "Dispatching", **fields):
		return self.make_action(status=status, dispatched_at=frappe.utils.now_datetime(), **fields)

	def observe(self, status: str) -> None:
		"""Save the status as an Atlas report does, so Frappe keeps a Version for it."""
		self.server.reload()
		self.server.status = status
		# Frappe skips Versions in tests unless asked; record_observed_state asks on a real change.
		self.server.save(ignore_version=False)

	def test_disk_only_resize_has_no_stop_step(self):
		progress = self.dispatch(request_payload=DISK_ONLY_PAYLOAD).get_resize_progress()

		self.assertEqual(
			[step["label"] for step in progress["steps"]],
			["Sending request", "Applying new size", "Starting server"],
		)
		self.assertEqual(states(progress), ["done", "current", "pending"])

	def test_queued_resize_waits_to_be_sent(self):
		action = self.make_action()
		progress = action.get_resize_progress()

		self.assertEqual(states(progress), ["current", "pending", "pending", "pending"])
		self.assertEqual(progress["target"], TARGET)
		self.assertEqual(progress["started_at"], action.creation)
		self.assertIsNone(progress["error"])

	def test_running_server_waits_for_the_stop(self):
		progress = self.dispatch().get_resize_progress()

		self.assertEqual(states(progress), ["done", "current", "pending", "pending"])

	def test_a_server_stopped_before_the_resize_waits_for_the_new_size(self):
		self.observe("Stopped")
		progress = self.dispatch().get_resize_progress()

		self.assertEqual(states(progress), ["done", "done", "current", "pending"])

	def test_a_stop_before_the_resize_is_not_its_stop(self):
		self.observe("Stopped")
		self.observe("Running")
		progress = self.dispatch().get_resize_progress()

		self.assertEqual(states(progress), ["done", "current", "pending", "pending"])

	def test_a_server_running_again_after_the_stop_is_starting(self):
		action = self.dispatch()
		self.observe("Stopped")
		self.observe("Running")

		self.assertEqual(states(action.get_resize_progress()), ["done", "done", "done", "current"])

	def test_a_finished_resize_has_every_step_done(self):
		self.assertEqual(states(self.dispatch(status="Sent").get_resize_progress()), ["done"] * 4)

	def test_succeeded_resize_reports_nothing(self):
		self.assertIsNone(self.make_action(status="Succeeded").get_resize_progress())

	def test_failed_resize_keeps_the_failing_step_and_the_error(self):
		action = self.dispatch(status="Failed", error_code="ATLAS_REJECTED")
		self.observe("Stopped")

		progress = action.get_resize_progress()

		self.assertEqual(states(progress), ["done", "done", "current", "pending"])
		self.assertTrue(progress["error"])

	def test_a_restart_after_a_failed_resize_is_not_the_new_size(self):
		action = self.dispatch(status="Failed", error_code="ATLAS_REJECTED")
		self.observe("Stopped")
		self.observe("Running")

		self.assertEqual(states(action.get_resize_progress()), ["done", "done", "current", "pending"])

	def test_an_uncertain_resize_shows_no_error(self):
		progress = self.dispatch(status="Uncertain", error_code="OUTCOME_UNKNOWN").get_resize_progress()

		self.assertIsNone(progress["error"])

	def test_a_server_stopped_before_the_resize_is_starting_once_it_runs(self):
		self.observe("Stopped")
		action = self.dispatch()
		self.observe("Running")

		self.assertEqual(states(action.get_resize_progress()), ["done", "done", "done", "current"])

	def test_overview_carries_the_resize_progress(self):
		self.dispatch()

		frappe.set_user(self.viewer)
		try:
			server = server_overview(team=self.team.name, resource_id=self.server.name)["server"]
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(states(server["resize_progress"]), ["done", "current", "pending", "pending"])

	def test_overview_hides_a_failure_older_than_a_day(self):
		self.dispatch(status="Failed", completed_at=frappe.utils.add_days(frappe.utils.now_datetime(), -2))

		server = server_overview(team=self.team.name, resource_id=self.server.name)["server"]

		self.assertIsNone(server["resize_progress"])

	def test_registry_names_the_pending_resize_step(self):
		self.dispatch()

		frappe.set_user(self.viewer)
		try:
			rows = registry(team=self.team.name)["servers"]
		finally:
			frappe.set_user("Administrator")

		self.assertEqual([row["resize_step"] for row in rows], ["Stopping server"])

	def test_no_resize_shows_no_progress(self):
		frappe.set_user(self.viewer)
		try:
			server = server_overview(team=self.team.name, resource_id=self.server.name)["server"]
			rows = registry(team=self.team.name)["servers"]
		finally:
			frappe.set_user("Administrator")

		self.assertIsNone(server["resize_progress"])
		self.assertIsNone(rows[0]["resize_step"])


def states(progress: dict) -> list[str]:
	return [step["state"] for step in progress["steps"]]
