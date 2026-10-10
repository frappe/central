import frappe
from frappe.tests import IntegrationTestCase

from central.api.servers import rename_server
from central.infrastructure.doctype.virtual_machine.virtual_machine import MAXIMUM_TITLE_LENGTH
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance


class TestServerRename(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("rename.owner@example.test")
		self.developer = ensure_user("rename.developer@example.test")
		self.viewer = ensure_user("rename.viewer@example.test")
		self.team_a = self._team("Rename A", {self.developer: "Developer", self.viewer: "Viewer"})
		self.team_b = self._team("Rename B", {})
		region = ensure_atlas_instance("blr-rename")
		self.server_a = self._server("vm-rename-a", self.team_a, region)
		self.server_b = self._server("vm-rename-b", self.team_b, region)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _team(self, name: str, roles: dict[str, str]) -> str:
		existing = frappe.db.get_value("Team", {"team_name": name})
		if existing:
			return existing

		members = [{"user": self.owner, "role": "Owner", "status": "Active"}]
		members += [{"user": user, "role": role, "status": "Active"} for user, role in roles.items()]
		return (
			frappe.get_doc(
				{"doctype": "Team", "team_name": name, "owner_user": self.owner, "members": members}
			)
			.insert()
			.name
		)

	def _server(self, resource_id: str, team: str, region: str) -> str:
		if frappe.db.exists("Virtual Machine", resource_id):
			frappe.delete_doc("Virtual Machine", resource_id, force=True, ignore_permissions=True)

		return (
			frappe.get_doc(
				{
					"doctype": "Virtual Machine",
					"resource_id": resource_id,
					"title": "before",
					"team": team,
					"region": region,
					"status": "Running",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def rename_as(self, user: str, team: str, resource_id: str, title: str) -> dict:
		frappe.set_user(user)
		try:
			return rename_server(team=team, resource_id=resource_id, title=title)
		finally:
			frappe.set_user("Administrator")

	def test_a_member_who_can_resize_renames_and_leaves_a_version(self):
		result = self.rename_as(self.developer, self.team_a, self.server_a, "  billing worker  ")

		self.assertEqual(result, {"title": "billing worker"})
		self.assertEqual(frappe.db.get_value("Virtual Machine", self.server_a, "title"), "billing worker")
		self.assertTrue(
			frappe.db.exists("Version", {"ref_doctype": "Virtual Machine", "docname": self.server_a})
		)

	def test_a_member_without_resize_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			self.rename_as(self.viewer, self.team_a, self.server_a, "renamed")

	def test_another_teams_server_is_refused(self):
		# A team-wide grant in team A passes the guard, so the team-scoped lookup refuses it.
		for team, server in ((self.team_a, self.server_b), (self.team_b, self.server_b)):
			with (
				self.subTest(team=team),
				self.assertRaises((frappe.PermissionError, frappe.DoesNotExistError)),
			):
				self.rename_as(self.developer, team, server, "renamed")

		self.assertEqual(frappe.db.get_value("Virtual Machine", self.server_b, "title"), "before")

	def test_a_blank_long_or_markup_title_is_refused(self):
		for title in ("", "   ", None, "x" * (MAXIMUM_TITLE_LENGTH + 1), "<img src=x onerror=alert(1)>"):
			with self.subTest(title=title), self.assertRaises(frappe.ValidationError):
				self.rename_as(self.developer, self.team_a, self.server_a, title)

		self.assertEqual(frappe.db.get_value("Virtual Machine", self.server_a, "title"), "before")
