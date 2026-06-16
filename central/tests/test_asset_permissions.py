import frappe
from frappe.tests import IntegrationTestCase

from central.tests.test_iam import ensure_user


class TestAssetPermissions(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("assetperm.owner@example.test")
		self.viewer = ensure_user("assetperm.viewer@example.test")
		self.team_a = self._team("Asset Perm A", self.viewer, "Viewer")
		self.team_b = self._team("Asset Perm B", self.owner, "Owner")
		self.cluster = self._cluster("blr-perm")
		self.asset_a = self._asset("vm-perm-a", self.team_a.name)
		self.asset_b = self._asset("vm-perm-b", self.team_b.name)

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
		if not frappe.db.exists("Atlas Instance", region):
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

	def _asset(self, rid, team):
		if frappe.db.exists("Asset", rid):
			frappe.delete_doc("Asset", rid, force=True, ignore_permissions=True)
		return frappe.get_doc(
			{
				"doctype": "Asset",
				"resource_id": rid,
				"team": team,
				"cluster": self.cluster,
				"status": "Running",
			}
		).insert(ignore_permissions=True)

	def test_member_sees_only_their_team_assets(self):
		frappe.set_user(self.viewer)
		try:
			names = set(frappe.get_list("Asset", pluck="name"))
		finally:
			frappe.set_user("Administrator")
		self.assertIn("vm-perm-a", names)
		self.assertNotIn("vm-perm-b", names)

	def test_member_can_read_but_not_write(self):
		frappe.set_user(self.viewer)
		try:
			self.assertTrue(frappe.has_permission("Asset", "read", self.asset_a.name))
			self.assertFalse(frappe.has_permission("Asset", "write", self.asset_a.name))
		finally:
			frappe.set_user("Administrator")

	def test_operator_sees_all_assets(self):
		names = set(frappe.get_list("Asset", pluck="name"))
		self.assertIn("vm-perm-a", names)
		self.assertIn("vm-perm-b", names)
