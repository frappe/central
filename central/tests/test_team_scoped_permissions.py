import frappe
from frappe.desk.reportview import execute as reportview_execute
from frappe.tests import IntegrationTestCase

from central.tests.test_iam import ensure_user


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
		region = f"scope-{self.suffix}"
		frappe.get_doc(
			{
				"doctype": "Atlas Instance",
				"region": region,
				"base_url": "https://atlas.example.test",
				"status": "Active",
				"api_key": "k",
				"api_secret": "s",
			}
		).insert()
		return region

	def _site(self, label: str, team: str):
		return frappe.get_doc(
			{
				"doctype": "Site",
				"site_name": f"{label}-{self.suffix}.example.test",
				"team": team,
				"cluster": self.cluster,
				"status": "Running",
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
