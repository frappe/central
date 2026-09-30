import frappe
from frappe.tests import IntegrationTestCase

from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance


class TestVirtualMachinePermissions(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("serverperm.owner@example.test")
		self.viewer = ensure_user("serverperm.viewer@example.test")
		self.team_a = self._team("VM Perm A", self.viewer, "Viewer")
		self.team_b = self._team("VM Perm B", self.owner, "Owner")
		self.cluster = self._cluster("blr-perm")
		self.server_a = self._server("vm-perm-a", self.team_a.name)
		self.server_b = self._server("vm-perm-b", self.team_b.name)

	def _team(self, name, user, role):
		existing = frappe.db.get_value("Team", {"team_name": name})
		if existing:
			return frappe.get_doc("Team", existing)
		members = [{"user": self.owner, "role": "Owner", "status": "Active"}]
		if user != self.owner:
			members.append({"user": user, "role": role, "status": "Active"})
		return frappe.get_doc(
			{"doctype": "Team", "team_name": name, "owner_user": self.owner, "members": members}
		).insert()

	def _cluster(self, region):
		return ensure_atlas_instance(region)

	def _server(self, rid, team):
		if frappe.db.exists("Virtual Machine", rid):
			frappe.delete_doc("Virtual Machine", rid, force=True, ignore_permissions=True)
		return frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": rid,
				"team": team,
				"region": self.cluster,
				"status": "Running",
			}
		).insert(ignore_permissions=True)

	def test_member_sees_only_their_team_servers(self):
		frappe.set_user(self.viewer)
		try:
			names = set(frappe.get_list("Virtual Machine", pluck="name"))
		finally:
			frappe.set_user("Administrator")
		self.assertIn("vm-perm-a", names)
		self.assertNotIn("vm-perm-b", names)

	def test_member_can_read_but_not_write(self):
		frappe.set_user(self.viewer)
		try:
			self.assertTrue(frappe.has_permission("Virtual Machine", "read", self.server_a.name))
			self.assertFalse(frappe.has_permission("Virtual Machine", "write", self.server_a.name))
		finally:
			frappe.set_user("Administrator")

	def test_operator_sees_all_servers(self):
		names = set(frappe.get_list("Virtual Machine", pluck="name"))
		self.assertIn("vm-perm-a", names)
		self.assertIn("vm-perm-b", names)
