import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.activity.servers import record_snapshot_terminal
from central.api.activity import server_activity, team_activity
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance, ensure_server

SSH_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEyR3oG8TTUg+l+6tzlA0cNYOkuvNHxFDLac2jrQ8eVg test"
SSH_KEY_2 = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIClV+IyjWRAC6lzReJlqj9T1vrp/hxhGZUEL78dShVbn test2"


class ActivityTestBase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.enterContext(patch("frappe.enqueue_doc"))
		self.enterContext(patch("frappe.enqueue"))
		self.enterContext(patch("frappe.sendmail"))

		suffix = frappe.generate_hash(length=6)
		self.owner = ensure_user(f"activity.owner.{suffix}@example.test")
		self.viewer = ensure_user(f"activity.viewer.{suffix}@example.test")
		self.outsider = ensure_user(f"activity.outsider.{suffix}@example.test")
		self.team = self._team(f"Activity {suffix}", {self.owner: "Owner", self.viewer: "Viewer"})
		self.other_team = self._team(f"Activity other {suffix}", {self.outsider: "Owner"})
		ensure_atlas_instance("activity-test")

		self.server = ensure_server(
			"activity-" + frappe.generate_hash(length=8),
			self.team,
			region="activity-test",
			atlas_vm_id="vm-activity-" + frappe.generate_hash(length=8),
		)

	def _team(self, name: str, roles: dict[str, str]) -> str:
		members = [{"user": user, "role": role, "status": "Active"} for user, role in roles.items()]
		owner = next(user for user, role in roles.items() if role == "Owner")
		return (
			frappe.get_doc({"doctype": "Team", "team_name": name, "owner_user": owner, "members": members})
			.insert()
			.name
		)

	def _action(self, action: str, status: str = "Succeeded", server: str | None = None) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Resource Action",
					"action": action,
					"resource_type": "Server",
					"team": self.team,
					"server": server or self.server,
					"resource_id": server or self.server,
					"region": "activity-test",
					"status": status,
					"requested_by": self.owner,
					"is_free_trial": 0,
					"correlation_id": frappe.generate_hash(length=12),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _version(self, data: dict, owner: str | None = None) -> str:
		frappe.set_user(owner or self.owner)
		try:
			return (
				frappe.get_doc(
					{
						"doctype": "Version",
						"ref_doctype": "Virtual Machine",
						"docname": self.server,
						"data": json.dumps(data),
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		finally:
			frappe.set_user("Administrator")

	def _snapshot(self, status: str = "Deleted", changed_at: str | None = None) -> str:
		name = (
			frappe.get_doc(
				{
					"doctype": "VM Snapshot",
					"team": self.team,
					"server": self.server,
					"snapshot_type": "Manual",
					"title": "Before upgrade",
					"requested_by": self.owner,
					"size_mib": 512,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		frappe.db.set_value("VM Snapshot", name, "status", status, update_modified=False)
		if changed_at:
			frappe.db.set_value("VM Snapshot", name, "modified", changed_at, update_modified=False)

		# db_set skips the hook, so ingest the settled state the way the patch does.
		record_snapshot_terminal(frappe.get_doc("VM Snapshot", name))
		return name

	def _latest_event(self, event: str, **filters):
		name = frappe.get_all(
			"Activity Event",
			filters={"event": event, **filters},
			order_by="creation desc",
			pluck="name",
			limit=1,
		)
		self.assertTrue(name, f"No {event} event found")
		return frappe.get_doc("Activity Event", name[0])

	def _events(self, **kwargs) -> list:
		frappe.set_user(self.owner)
		return server_activity(team=self.team, resource_id=self.server, **kwargs)["events"]

	def _team_events(self, user: str, **kwargs) -> list:
		frappe.set_user(user)
		return team_activity(team=self.team, **kwargs)["events"]

	def _backdate_event(self, reference_name: str, when: str) -> None:
		frappe.db.set_value(
			"Activity Event", {"reference_name": reference_name}, "occurred_at", when, update_modified=False
		)

	def _add_member(self, user: str, role: str, **scope) -> None:
		frappe.set_user(self.owner)
		team = frappe.get_doc("Team", self.team)
		team.append("members", {"user": user, "role": role, "status": "Active", **scope})
		team.save()
