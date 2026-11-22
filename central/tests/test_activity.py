from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.activity import server_activity, team_activity
from central.api.snapshots import set_automatic_snapshots
from central.central.doctype.activity_event.activity_event import (
	ACTION,
	ActivityEvent,
	get_action_details,
	get_actor,
	get_event,
	get_retention_days,
)
from central.central.doctype.activity_event.backfill import backfill
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.patches.v0_0.fill_resize_activity_details import execute as fill_resize_activity_details
from central.resource_actions import submit_command
from central.tests.test_iam import ensure_user
from central.tests.test_server_overview import make_public_key
from central.tests.utils import ensure_atlas_instance


class TestActivity(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		self.enterContext(patch("frappe.db.commit"))
		self.enterContext(patch.object(VirtualMachine, "sync_subscription_on_status_change"))

		self.admin = ensure_user("activity.admin@example.test")
		self.viewer = ensure_user("activity.viewer@example.test")
		self.outsider = ensure_user("activity.outsider@example.test")
		self.team = self._team("Activity A", {self.admin: "Admin", self.viewer: "Viewer"})
		self.other_team = self._team("Activity B", {self.outsider: "Admin"})
		self.server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": "activity-" + frappe.generate_hash(length=8),
				"team": self.team.name,
				"atlas_vm_id": "vm-activity",
				"region": ensure_atlas_instance("test-activity"),
				"status": "Running",
			}
		).insert()

	def _team(self, name: str, roles: dict[str, str]):
		members = [{"user": user, "role": role, "status": "Active"} for user, role in roles.items()]
		return frappe.get_doc(
			{"doctype": "Team", "team_name": name, "owner_user": "Administrator", "members": members}
		).insert()

	def _team_events(self, user: str, **filters) -> list[str]:
		frappe.set_user(user)
		events = [event["event"] for event in team_activity(team=self.team.name, **filters)["events"]]
		frappe.set_user("Administrator")
		return events

	def _rename_server(self, title: str) -> None:
		self.server.title = title
		self.server.save(ignore_version=False)

	def test_each_member_sees_only_the_events_their_capabilities_allow(self):
		self.team.team_name = "Activity A renamed"
		self.team.append("members", {"user": self.outsider, "role": "Viewer", "status": "Active"})
		self.team.save(ignore_version=False)
		self._rename_server("Renamed server")
		self.other_team.team_name = "Activity B renamed"
		self.other_team.save(ignore_version=False)

		# One save writes its events together, so their order within the save is not fixed.
		self.assertCountEqual(
			self._team_events(self.admin),
			["server.renamed", "team.renamed", "team.member_added", "team.created"],
		)
		self.assertEqual(self._team_events(self.viewer), ["server.renamed"])

	def test_one_save_splits_into_events_with_their_own_capability(self):
		key = frappe.get_doc(
			{
				"doctype": "Team SSH Key",
				"team": self.team.name,
				"title": "Laptop",
				"public_key": make_public_key(),
			}
		).insert()
		self.server.title = "Build box"
		self.server.append("ssh_keys", {"team_ssh_key": key.name})
		self.server.save(ignore_version=False)

		frappe.set_user(self.viewer)
		events = server_activity(team=self.team.name, resource_id=self.server.resource_id)["events"]
		self.assertEqual([event["event"] for event in events], ["server.renamed"])

		frappe.set_user(self.admin)
		events = server_activity(team=self.team.name, resource_id=self.server.resource_id, category="access")
		self.assertEqual(
			events["events"][0]["details"], [{"label": "SSH keys", "from": None, "to": "Laptop"}]
		)

	def test_a_switch_stored_inverted_reads_as_its_label(self):
		frappe.set_user(self.admin)
		set_automatic_snapshots(team=self.team.name, resource_id=self.server.resource_id, enabled=0)

		events = server_activity(team=self.team.name, resource_id=self.server.resource_id)["events"]
		self.assertEqual(events[0]["details"], [{"label": "Automatic snapshots", "from": "on", "to": "off"}])

	def test_a_job_reads_without_a_person(self):
		self._rename_server("Renamed by a job")

		frappe.set_user(self.admin)
		event = server_activity(team=self.team.name, resource_id=self.server.resource_id)["events"][0]
		self.assertEqual((event["actor"]["label"], event["sentence"]), ("", "{resource} was renamed"))

	def test_a_region_report_names_who_initiated_it(self):
		snapshot = frappe.get_doc(
			{
				"doctype": "VM Snapshot",
				"title": "Before upgrade",
				"team": self.team.name,
				"server": self.server.name,
				"snapshot_type": "Manual",
				"requested_by": self.admin,
			}
		).insert()
		snapshot.status = "Available"
		snapshot.save(ignore_version=False)

		frappe.set_user(self.viewer)
		event = server_activity(team=self.team.name, resource_id=self.server.resource_id)["events"][0]
		self.assertEqual(event["event"], "snapshot.available")
		self.assertEqual(event["initiator"]["label"], "activity.admin")

	def test_an_operator_reads_as_frappe_cloud_to_customers_only(self):
		operator = ensure_user("activity.operator@example.test")
		frappe.get_doc("User", operator).add_roles("System Manager")
		frappe.set_user(operator)
		self._rename_server("Renamed by support")

		frappe.set_user(self.admin)
		event = server_activity(team=self.team.name, resource_id=self.server.resource_id)["events"][0]
		self.assertEqual(event["actor"]["label"], "Frappe Cloud")
		self.assertIsNone(event["initiator"])

		frappe.set_user(operator)
		event = server_activity(team=self.team.name, resource_id=self.server.resource_id)["events"][0]
		self.assertEqual(event["actor"]["label"], "activity.operator")

	def test_a_guest_session_names_the_person_on_the_record(self):
		# An older sign-up created the team before its owner had a session.
		team = frappe.get_doc({"doctype": "Team", "name": "TEAM-GUEST", "owner_user": self.admin})
		self.assertEqual(get_actor(team, "Guest"), self.admin)
		# A region report on a server has no person, signed in or not.
		self.assertIsNone(get_actor(self.server, "Guest"))

	def test_a_member_who_leaves_reads_as_leaving(self):
		frappe.set_user(self.viewer)
		for row in [row for row in self.team.members if row.user == self.viewer]:
			self.team.remove(row)
		self.team.save(ignore_permissions=True, ignore_version=False)

		event = frappe.get_last_doc(
			"Activity Event", filters={"team": self.team.name, "event": "team.member_left"}
		)
		self.assertEqual(
			(event.actor, event.resource_label), (self.viewer, frappe.utils.get_fullname(self.viewer))
		)

	def test_a_member_of_another_team_cannot_read_the_feed(self):
		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			team_activity(team=self.team.name)

	def test_a_deleted_resource_keeps_its_history(self):
		key = frappe.get_doc(
			{
				"doctype": "Team SSH Key",
				"team": self.team.name,
				"title": "Old laptop",
				"public_key": make_public_key(),
			}
		).insert()
		key.delete()

		frappe.set_user(self.admin)
		events = team_activity(team=self.team.name, category="access")["events"]
		self.assertEqual([event["event"] for event in events], ["ssh_key.deleted", "ssh_key.created"])
		self.assertEqual({event["resource"]["label"] for event in events}, {"Old laptop"})

	@patch("frappe.enqueue")
	def test_an_action_records_only_its_end_state(self, enqueue):
		frappe.set_user(self.admin)
		submit_command("restart", self.team.name, self.server.name)
		frappe.set_user("Administrator")

		action = frappe.get_last_doc("Resource Action", filters={"server": self.server.name})
		action.set_status("In Progress")
		action.set_status("Succeeded")

		events = self._team_events(self.admin, category="action")
		self.assertEqual(events, ["server.restarted"])
		event = frappe.get_last_doc("Activity Event", filters={"event": "server.restarted"})
		self.assertEqual((event.actor, event.status), (self.admin, "Succeeded"))

	@patch("frappe.enqueue")
	def test_a_failed_action_says_it_was_tried(self, enqueue):
		frappe.set_user(self.admin)
		submit_command("restart", self.team.name, self.server.name)
		frappe.set_user("Administrator")

		frappe.get_last_doc("Resource Action", filters={"server": self.server.name}).set_status("Failed")

		frappe.set_user(self.admin)
		event = team_activity(team=self.team.name, category="action")["events"][0]
		self.assertEqual(
			(event["event"], event["sentence"]),
			("server.restart_failed", "{actor} tried to restart {resource}"),
		)

	def test_a_resize_lists_each_size_that_changed(self):
		def get_changes(from_shape: dict | None, shape: dict) -> list[tuple]:
			action = frappe.get_doc(
				{
					"doctype": "Resource Action",
					"action": "resize",
					"status": "Succeeded",
					"request_payload": frappe.as_json({"shape": shape, "from_shape": from_shape}),
				}
			)
			return [(detail["label"], detail["from"], detail["to"]) for detail in get_action_details(action)]

		small = {"vcpus": 2.0, "memory_megabytes": 4096, "disk_gigabytes": 50}
		self.assertEqual(get_changes(small, {**small, "disk_gigabytes": 100}), [("Disk", "50 GB", "100 GB")])
		self.assertEqual(
			get_changes(small, {**small, "vcpus": 0.5, "memory_megabytes": 8192}),
			[("vCPU", "2", "0.5"), ("Memory", "4 GB", "8 GB")],
		)
		self.assertEqual(
			get_changes(None, small),
			[("vCPU", None, "2"), ("Memory", None, "4 GB"), ("Disk", None, "50 GB")],
		)

	@patch("frappe.enqueue")
	def test_past_resize_events_get_their_size_once_and_again(self, enqueue):
		frappe.set_user(self.admin)
		submit_command("restart", self.team.name, self.server.name)
		frappe.set_user("Administrator")

		action = frappe.get_last_doc("Resource Action", filters={"server": self.server.name})
		shape = {"vcpus": 2.0, "memory_megabytes": 4096, "disk_gigabytes": 50}
		payload = {"shape": {**shape, "disk_gigabytes": 100}, "from_shape": shape}
		action.db_set({"action": "resize", "status": "Succeeded", "request_payload": frappe.as_json(payload)})
		ActivityEvent.insert_events(
			[get_event(self.server, "server.resized", ACTION, reference=("Resource Action", action.name))]
		)
		event = frappe.get_last_doc("Activity Event", filters={"event": "server.resized"})
		self.assertIsNone(event.details)

		for _run in range(2):
			fill_resize_activity_details()
			details = frappe.parse_json(frappe.db.get_value("Activity Event", event.name, "details"))
			self.assertEqual(details, [{"label": "Disk", "from": "50 GB", "to": "100 GB"}])

	def test_pages_follow_the_cursor_without_gaps(self):
		for title in ("One", "Two", "Three"):
			self._rename_server(title)

		frappe.set_user(self.admin)
		first = server_activity(team=self.team.name, resource_id=self.server.resource_id, limit=2)
		second = server_activity(
			team=self.team.name, resource_id=self.server.resource_id, limit=2, cursor=first["next_cursor"]
		)

		labels = [event["details"][0]["to"] for event in first["events"] + second["events"]]
		self.assertEqual(labels, ["Three", "Two", "One"])
		self.assertIsNone(second["next_cursor"])

	def test_a_cached_feed_shows_a_new_event(self):
		self.assertEqual(self._team_events(self.viewer), [])

		self._rename_server("After the first read")

		self.assertEqual(self._team_events(self.viewer), ["server.renamed"])

	def test_history_from_before_the_feed_is_replayed_once_at_its_own_time(self):
		started = self.team.creation
		self._rename_server("Before the feed")
		key = frappe.get_doc(
			{
				"doctype": "Team SSH Key",
				"team": self.team.name,
				"title": "Gone",
				"public_key": make_public_key(),
			}
		).insert()
		key.delete()
		version = frappe.get_last_doc(
			"Version", filters={"ref_doctype": "Virtual Machine", "docname": self.server.name}
		)
		# The feed starts empty, as on the day it is deployed.
		frappe.db.delete("Activity Event")

		with patch.dict(frappe.flags, {"in_patch": True}):
			backfill()
			backfill()

		events = frappe.get_all(
			"Activity Event",
			filters={"team": self.team.name, "creation": (">=", started)},
			fields=["event", "creation"],
		)
		# A deleted key has no record left to show its creation, only its deletion.
		self.assertCountEqual(
			[event.event for event in events], ["team.created", "server.renamed", "ssh_key.deleted"]
		)
		renamed = next(event for event in events if event.event == "server.renamed")
		self.assertEqual(renamed.creation, version.creation)

	def test_log_settings_owns_the_retention(self):
		# Saving Log Settings adds the default row from hooks; an operator then edits its days.
		settings = frappe.get_single("Log Settings")
		settings.save()
		row = next(row for row in settings.logs_to_clear if row.ref_doctype == "Activity Event")
		self.assertEqual((row.days, get_retention_days()), (365, 365))

		row.days = 90
		settings.save()
		self.assertEqual(get_retention_days(), 90)

		# Before Frappe adds the row, as during the first migrate, the hooks default applies.
		frappe.db.delete("Logs To Clear", {"parent": "Log Settings", "ref_doctype": "Activity Event"})
		self.assertEqual(get_retention_days(), 365)
