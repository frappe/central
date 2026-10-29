import json

import frappe
from frappe.utils import add_days, now_datetime

from central.activity.backfill import backfill_server_events
from central.activity.servers import get_action_details, get_setting_detail
from central.api.activity import _decode_cursor, _details, _encode_cursor, server_activity
from central.central.doctype.activity_event.activity_event import ActivityEvent
from central.permissions import activity_event_query_conditions, has_activity_event_permission
from central.tests.activity_test_base import ActivityTestBase
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_server


class TestActivity(ActivityTestBase):
	def test_hooks_record_created_and_settled(self):
		action = self._action("start", status="Queued")
		self.assertFalse(
			frappe.db.exists("Activity Event", {"server": self.server, "event": "server.started"})
		)

		frappe.set_user(self.owner)
		frappe.get_doc("Resource Action", action).transition("Succeeded")
		event = self._latest_event("server.started", server=self.server)
		self.assertEqual(event.status, "Succeeded")
		self.assertEqual(event.actor, self.owner)

		# one action is one event; a late status change cannot rewrite it
		frappe.get_doc("Resource Action", action).transition("Failed")
		self.assertEqual(
			frappe.db.count("Activity Event", {"server": self.server, "event": "server.started"}), 1
		)

		created = self._latest_event("server.created", server=self.server)
		self.assertIn(created.actor, ("Administrator", "Guest"))

	def test_each_category_renders(self):
		self._action("restart")
		version = self._version(
			{
				"changed": [
					["plan", "Starter", "Performance"],
					["vcpus", 1, 2],
					["state_observed_at", "old", "new"],
					["firewall_rules", "{}", '{"rules": []}'],
				],
				"added": [],
				"removed": [],
				"row_changed": [],
			}
		)
		self._snapshot()

		events = {event["event"]: event for event in self._events(limit=100)}

		restart = events["server.restarted"]
		self.assertEqual(restart["title"], "Server restarted")
		self.assertEqual(restart["status"], "Succeeded")
		self.assertEqual(restart["actor"]["label"], frappe.db.get_value("User", self.owner, "full_name"))
		self.assertEqual(restart["actor"]["kind"], "user")

		config = events["server.configured"]
		self.assertEqual(config["title"], "Configuration changed")
		details = {detail["label"]: detail for detail in config["details"]}
		self.assertEqual(details["Plan"]["from"], "Starter")
		self.assertEqual(details["Plan"]["to"], "Performance")
		self.assertEqual(details["vCPUs"]["from"], "1")
		self.assertEqual(details["vCPUs"]["to"], "2")
		self.assertNotIn("state_observed_at", details)
		self.assertEqual(details["Firewall rules"]["from"], None)
		self.assertEqual(details["Firewall rules"]["to"], None)

		snapshot = events["snapshot.deleted"]
		self.assertEqual(snapshot["title"], "Snapshot deleted")
		self.assertEqual(
			snapshot["details"],
			[
				{"label": "Snapshot", "from": None, "to": "Before upgrade"},
				{"label": "Size", "from": None, "to": "512 MiB"},
			],
		)

		created = events["server.created"]
		self.assertEqual(created["actor"]["kind"], "system")
		self.assertTrue(
			frappe.db.get_value("Activity Event", {"reference_name": version}, "event_key").endswith(
				f"version:{version}"
			)
		)

	def test_category_filter_returns_one_kind(self):
		self._action("restart")
		self._snapshot()

		self.assertEqual({event["category"] for event in self._events(category="action")}, {"action"})
		self.assertEqual({event["category"] for event in self._events(category="snapshot")}, {"snapshot"})
		with self.assertRaises(frappe.ValidationError):
			self._events(category="nonsense")

	def test_another_teams_server_is_refused(self):
		foreign = ensure_server(
			"activity-foreign-" + frappe.generate_hash(length=8),
			self.other_team,
			region="activity-test",
			atlas_vm_id="vm-foreign-" + frappe.generate_hash(length=8),
		)

		frappe.set_user(self.owner)
		with self.assertRaises(frappe.DoesNotExistError):
			server_activity(team=self.team, resource_id=foreign)

	def test_server_activity_permissions_follow_server_view(self):
		self._action("restart")
		event = self._latest_event("server.restarted", server=self.server)

		self.assertTrue(has_activity_event_permission(event, user=self.owner, ptype="read"))
		self.assertTrue(has_activity_event_permission(event, user=self.viewer, ptype="read"))
		self.assertFalse(has_activity_event_permission(event, user=self.outsider, ptype="read"))
		self.assertFalse(has_activity_event_permission(event, user=self.owner, ptype="write"))
		self.assertFalse(has_activity_event_permission(event, user="Administrator", ptype="delete"))

		conditions = activity_event_query_conditions(self.viewer)
		self.assertIn(self.team, conditions)
		self.assertIn("server:view", conditions)
		self.assertNotIn(self.other_team, activity_event_query_conditions(self.owner))

		frappe.set_user(self.viewer)
		self.assertIn(
			event.name,
			{row["id"] for row in server_activity(team=self.team, resource_id=self.server)["events"]},
		)
		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			server_activity(team=self.team, resource_id=self.server)

	def test_scoped_grant_limits_server_events(self):
		scoped = ensure_user(f"activity.scoped.{frappe.generate_hash(length=6)}@example.test")
		self._add_member(scoped, "Viewer", resource_type="Server", resource_name=self.server)
		other_server = ensure_server(
			"activity-other-" + frappe.generate_hash(length=8),
			self.team,
			region="activity-test",
			atlas_vm_id="vm-other-" + frappe.generate_hash(length=8),
		)
		self._action("restart", server=self.server)
		self._action("restart", server=other_server)

		visible = self._latest_event("server.restarted", server=self.server)
		hidden = self._latest_event("server.restarted", server=other_server)
		self.assertTrue(has_activity_event_permission(visible, user=scoped, ptype="read"))
		self.assertFalse(has_activity_event_permission(hidden, user=scoped, ptype="read"))

		conditions = activity_event_query_conditions(scoped)
		self.assertIn(self.server, conditions)
		self.assertNotIn(other_server, conditions)

		frappe.set_user(scoped)
		self.assertIn(
			visible.name,
			{row["id"] for row in server_activity(team=self.team, resource_id=self.server)["events"]},
		)
		with self.assertRaises(frappe.PermissionError):
			server_activity(team=self.team, resource_id=other_server)

	def test_ip_is_recorded_for_the_request_actor(self):
		frappe.local.request_ip = "203.0.113.9"
		self.addCleanup(setattr, frappe.local, "request_ip", None)
		frappe.set_user(self.owner)
		self._action("restart")

		event = self._latest_event("server.restarted", server=self.server)
		self.assertEqual(
			frappe.db.get_value("Activity Event IP", {"event": event.name}, "ip_address"),
			"203.0.113.9",
		)

		created = self._latest_event("server.created", server=self.server)
		self.assertFalse(frappe.db.exists("Activity Event IP", {"event": created.name}))

		frappe.set_user(self.owner)
		body = server_activity(team=self.team, resource_id=self.server)["events"]
		self.assertEqual(next(row for row in body if row["id"] == event.name)["ip_address"], "203.0.113.9")

		frappe.set_user(self.viewer)
		body = server_activity(team=self.team, resource_id=self.server)["events"]
		self.assertNotIn("ip_address", next(row for row in body if row["id"] == event.name))
		self.assertFalse(frappe.has_permission("Activity Event IP", ptype="read", user=self.viewer))

	def test_dedupe_and_unknown_event(self):
		key = f"manual-{frappe.generate_hash(length=8)}"
		first = ActivityEvent.record("member.added", resource_type="Team", resource_name=self.team, key=key)
		second = ActivityEvent.record("member.added", resource_type="Team", resource_name=self.team, key=key)
		self.assertTrue(first)
		self.assertIsNone(second)
		self.assertEqual(frappe.db.count("Activity Event", {"event_key": f"member.added:{key}"}), 1)

		with self.assertRaises(KeyError):
			ActivityEvent.record("nope", resource_type="Team", resource_name=self.team, key=key)

	def test_long_event_keys_fit_the_column(self):
		name = ActivityEvent.record(
			"team.updated", resource_type="Team", resource_name=self.team, key="x" * 500
		)
		self.assertTrue(name)
		event_key = frappe.db.get_value("Activity Event", name, "event_key")
		self.assertLessEqual(len(event_key), 140)
		self.assertTrue(event_key.startswith("team.updated:"))

	def test_retention_deletes_only_old_rows(self):
		suffix = frappe.generate_hash(length=8)
		old = ActivityEvent.record(
			"member.added", resource_type="Team", resource_name=self.team, key=f"old-{suffix}"
		)
		new = ActivityEvent.record(
			"member.added", resource_type="Team", resource_name=self.team, key=f"new-{suffix}"
		)
		old_time = add_days(now_datetime(), -40)
		frappe.db.set_value("Activity Event", old, "occurred_at", old_time)
		address = frappe.get_doc(
			{
				"doctype": "Activity Event IP",
				"event": old,
				"team": self.team,
				"ip_address": "203.0.113.10",
				"occurred_at": old_time,
			}
		).insert(ignore_permissions=True)

		ActivityEvent.clear_old_logs(30)
		self.assertFalse(frappe.db.exists("Activity Event", old))
		self.assertFalse(frappe.db.exists("Activity Event IP", address.name))
		self.assertTrue(frappe.db.exists("Activity Event", new))

	def test_backfill_is_idempotent(self):
		fields = ["name", "event", "occurred_at", "details", "status"]
		backfill_server_events()
		first = frappe.get_all(
			"Activity Event",
			filters={"server": self.server},
			fields=fields,
			order_by="name",
		)
		backfill_server_events()
		self.assertEqual(
			frappe.get_all(
				"Activity Event",
				filters={"server": self.server},
				fields=fields,
				order_by="name",
			),
			first,
		)
		self.assertGreaterEqual(len(first), 1)

	def test_backfill_skips_rows_before_retention(self):
		old = ensure_server(
			"activity-old-" + frappe.generate_hash(length=8),
			self.team,
			region="activity-test",
			atlas_vm_id="vm-old-" + frappe.generate_hash(length=8),
		)
		frappe.db.delete("Activity Event", {"server": old})
		frappe.db.delete("Version", {"ref_doctype": "Virtual Machine", "docname": old})
		frappe.db.set_value(
			"Virtual Machine", old, "creation", add_days(now_datetime(), -40), update_modified=False
		)

		backfill_server_events()
		self.assertFalse(frappe.db.exists("Activity Event", {"server": old}))

	def test_version_noise_only_is_dropped(self):
		self._version(
			{
				"changed": [["state_observed_at", "a", "b"], ["gateway_url", "x", "y"]],
				"added": [],
				"removed": [],
				"row_changed": [],
			}
		)
		self.assertEqual(
			frappe.db.count("Activity Event", {"server": self.server, "event": "server.configured"}), 0
		)

	def test_setting_change_records_one_event(self):
		server_doc = frappe.get_doc("Virtual Machine", self.server)

		from central.activity.servers import record_setting

		self.assertIsNotNone(record_setting(server_doc, "is_termination_protected", 0, 1))
		self.assertIsNone(record_setting(server_doc, "is_termination_protected", 1, 1))

		setting = frappe.db.get_value(
			"Activity Event",
			{
				"server": self.server,
				"event": "server.configured",
				"event_key": ["like", "server.configured:setting:%"],
			},
			"details",
		)
		self.assertEqual(
			json.loads(setting), [{"label": "Termination protection", "from": "off", "to": "on"}]
		)

	def test_automatic_snapshots_read_as_their_label(self):
		self.assertEqual(
			get_setting_detail("skip_automatic_snapshot", 1, 0),
			{"label": "Automatic snapshots", "from": "off", "to": "on"},
		)

	def test_deleted_snapshot_is_stamped_when_it_changed(self):
		self._snapshot(changed_at="2026-10-22 09:30:00.000000")
		occurred_at = frappe.db.get_value(
			"Activity Event", {"server": self.server, "event": "snapshot.deleted"}, "occurred_at"
		)
		self.assertEqual(str(occurred_at), "2026-10-22 09:30:00")

	def test_detail_rows_always_carry_both_values(self):
		self.assertEqual(
			_details(
				'[{"label": "Snapshot", "to": "Before upgrade"}, {"label": "vCPUs", "from": 1, "to": 2}]'
			),
			[
				{"label": "Snapshot", "from": None, "to": "Before upgrade"},
				{"label": "vCPUs", "from": "1", "to": "2"},
			],
		)

	def test_resize_details_follow_the_reported_shape(self):
		payload = json.dumps(
			{
				"shape": {"vcpus": 4, "memory_megabytes": 8192, "disk_gigabytes": 40},
				"from_shape": {"vcpus": 2, "memory_megabytes": 4096, "disk_gigabytes": 40},
			}
		)
		settled = frappe._dict(action="resize", status="Succeeded", request_payload=payload)
		failed = frappe._dict(action="resize", status="Failed", request_payload=payload)
		replanned = frappe._dict(
			action="resize",
			status="Succeeded",
			request_payload=json.dumps(
				{
					"plan": "plan-4vcpu",
					"from_plan": "plan-2vcpu",
					"shape": {"vcpus": 4, "memory_megabytes": 8192, "disk_gigabytes": 40},
					"from_shape": {"vcpus": 2, "memory_megabytes": 4096, "disk_gigabytes": 40},
				}
			),
		)

		self.assertEqual(
			get_action_details(settled),
			[
				{"label": "vCPUs", "from": "2", "to": "4"},
				{"label": "Memory", "from": "4096", "to": "8192"},
			],
		)
		self.assertEqual(get_action_details(failed), [])
		self.assertEqual(
			get_action_details(replanned),
			[
				{"label": "Plan", "from": "plan-2vcpu", "to": "plan-4vcpu"},
				{"label": "vCPUs", "from": "2", "to": "4"},
				{"label": "Memory", "from": "4096", "to": "8192"},
			],
		)

	def test_cursor_does_not_repeat_or_skip(self):
		actions = [self._action("restart"), self._action("start"), self._action("stop")]
		for action, when in zip(actions, ("09:00", "09:01", "09:02"), strict=False):
			self._backdate_event(action, f"2026-10-22 {when}:00.000000")

		frappe.set_user(self.owner)
		first = server_activity(team=self.team, resource_id=self.server, limit=2)
		self.assertEqual(len(first["events"]), 2)
		self.assertTrue(first["next_cursor"])

		second = server_activity(
			team=self.team, resource_id=self.server, limit=2, cursor=first["next_cursor"]
		)
		seen = [event["id"] for event in first["events"] + second["events"]]
		self.assertEqual(len(seen), len(set(seen)))
		self.assertEqual(
			{event["title"] for event in first["events"] + second["events"]},
			{"Server created", "Server started", "Server stopped", "Server restarted"},
		)

	def test_bad_cursor_is_a_validation_error(self):
		with self.assertRaises(frappe.ValidationError):
			server_activity(team=self.team, resource_id=self.server, cursor="not-a-cursor")

	def test_cursor_round_trip(self):
		event = {"id": "abc123", "occurred_at": "2026-10-22 10:00:00.000000"}
		self.assertEqual(
			_decode_cursor(_encode_cursor(event)),
			{"timestamp": "2026-10-22 10:00:00.000000", "name": "abc123"},
		)
