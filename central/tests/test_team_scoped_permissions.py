import frappe
from frappe.desk.reportview import execute as reportview_execute
from frappe.tests import IntegrationTestCase

from central.permissions import (
	pilot_credential_has_permission,
	pilot_credential_query_conditions,
	team_notification_has_permission,
	team_notification_query_conditions,
	team_service_has_permission,
	team_service_query_conditions,
)
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance


class TestTeamScopedPermissions(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("team.scope.owner@example.test")
		self.viewer = ensure_user("team.scope.viewer@example.test")
		self.other_user = ensure_user("team.scope.other@example.test")
		self.suffix = frappe.generate_hash(length=8)
		self.cluster = self._cluster()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_desk_list_apis_are_team_scoped(self):
		team_a = self._team("Team Scoped A", self.viewer, "Viewer")
		team_b = self._team("Team Scoped B", self.owner, "Owner")
		site_a = self._site("a", team_a.name)
		site_b = self._site("b", team_b.name)

		frappe.set_user(self.viewer)
		list_names = set(frappe.get_list("Site", pluck="name"))
		reportview_names = {row.name for row in reportview_execute("Site", fields=["name"])}

		self.assertIn(site_a.name, list_names)
		self.assertNotIn(site_b.name, list_names)
		self.assertIn(site_a.name, reportview_names)
		self.assertNotIn(site_b.name, reportview_names)
		self.assertTrue(frappe.has_permission("Site", "read", site_a.name))
		self.assertFalse(frappe.has_permission("Site", "read", site_b.name))
		self.assertFalse(frappe.has_permission("Site", "write", site_a.name))

	def test_permission_probe_lists_are_self_scoped(self):
		team = self._team("Probe Scoped", self.viewer, "Viewer")
		viewer_probe = self._probe(self.viewer, team.name, "server:view")
		other_probe = self._probe(self.other_user, team.name, "server:view")

		frappe.set_user(self.viewer)
		list_names = set(frappe.get_list("IAM Permission Probe", pluck="name"))
		reportview_names = {row.name for row in reportview_execute("IAM Permission Probe", fields=["name"])}

		self.assertIn(viewer_probe.name, list_names)
		self.assertNotIn(other_probe.name, list_names)
		self.assertIn(viewer_probe.name, reportview_names)
		self.assertNotIn(other_probe.name, reportview_names)
		self.assertTrue(frappe.has_permission("IAM Permission Probe", "read", viewer_probe.name))
		self.assertFalse(frappe.has_permission("IAM Permission Probe", "read", other_probe.name))

	def test_notification_preferences_are_owned_and_team_scoped(self):
		team = self._team("Preference Scoped", self.viewer, "Viewer")
		other_team = self._team("Other Preference Scoped", self.other_user, "Viewer")

		frappe.set_user(self.viewer)
		preference = frappe.get_doc(
			{
				"doctype": "User Notification Preference",
				"user": self.viewer,
				"team": team.name,
				"category": "Server",
			}
		).insert()
		other_preference = frappe.get_doc(
			{
				"doctype": "User Notification Preference",
				"user": self.other_user,
				"team": other_team.name,
				"category": "Server",
			}
		).insert(ignore_permissions=True)

		self.assertEqual(frappe.get_list("User Notification Preference", pluck="name"), [preference.name])
		self.assertTrue(frappe.has_permission("User Notification Preference", "read", preference.name))
		self.assertFalse(frappe.has_permission("User Notification Preference", "read", other_preference.name))

		preference.user = self.other_user
		with self.assertRaises(frappe.PermissionError):
			preference.save()
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "User Notification Preference",
					"user": self.viewer,
					"team": other_team.name,
					"category": "Billing",
				}
			).insert()

	def test_internal_team_records_remain_operator_only(self):
		frappe.set_user(self.viewer)
		for query_conditions, has_permission in (
			(pilot_credential_query_conditions, pilot_credential_has_permission),
			(team_notification_query_conditions, team_notification_has_permission),
			(team_service_query_conditions, team_service_has_permission),
		):
			with self.subTest(query_conditions=query_conditions.__name__):
				self.assertEqual(query_conditions(), "1 = 0")
				self.assertFalse(has_permission(frappe._dict(team="any-team")))

		frappe.set_user("Administrator")
		for query_conditions, has_permission in (
			(pilot_credential_query_conditions, pilot_credential_has_permission),
			(team_notification_query_conditions, team_notification_has_permission),
			(team_service_query_conditions, team_service_has_permission),
		):
			with self.subTest(query_conditions=query_conditions.__name__):
				self.assertEqual(query_conditions(), "")
				self.assertTrue(has_permission(frappe._dict(team="any-team")))

	def _team(self, label: str, user: str, role: str):
		members = [{"user": self.owner, "role": "Owner", "status": "Active"}]
		if user != self.owner:
			members.append({"user": user, "role": role, "status": "Active"})

		team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": f"{label} {self.suffix}",
				"owner_user": self.owner,
				"members": members,
			}
		)
		team.insert()
		return team

	def _cluster(self) -> str:
		return ensure_atlas_instance(f"scope-{self.suffix}")

	def _site(self, label: str, team: str):
		machine = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": f"server-{label}-{self.suffix}",
				"team": team,
				"cluster": self.cluster,
				"status": "Running",
			}
		).insert(ignore_permissions=True)
		return frappe.get_doc(
			{
				"doctype": "Site",
				"site_name": f"{label}-{self.suffix}.example.test",
				"team": team,
				"server": machine.name,
			}
		).insert(ignore_permissions=True)

	def _probe(self, user: str, team: str, capability: str):
		return frappe.get_doc(
			{
				"doctype": "IAM Permission Probe",
				"user": user,
				"team": team,
				"capability": capability,
			}
		).insert(ignore_permissions=True)
