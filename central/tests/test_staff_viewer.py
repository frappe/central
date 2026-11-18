from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.iam import can
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance
from central.users import ensure_staff_role_profile

STAFF_ROLES = ("Central User", "Staff Viewer")


def ensure_staff_viewer(email: str) -> str:
	"""A user with the roles of the Frappe Employee role profile."""
	frappe.get_doc("User", ensure_user(email)).add_roles(*STAFF_ROLES)
	return email


class TestStaffViewer(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=8)
		self.owner = ensure_user("staff.viewer.owner@example.test")
		self.staff = ensure_staff_viewer("staff.viewer@example.test")
		self.team = self._team()
		self.server = self._server()
		self.site = self._site()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_staff_viewer_reads_every_team_record(self):
		frappe.set_user(self.staff)

		for doc in (self.team, self.site, self.server):
			self.assertEqual(
				frappe.get_list(doc.doctype, filters={"name": doc.name}, pluck="name"), [doc.name]
			)
			self.assertTrue(frappe.has_permission(doc.doctype, "read", doc.name))

	def test_a_staff_viewer_changes_nothing(self):
		frappe.set_user(self.staff)

		for doc in (self.team, self.site, self.server):
			for ptype in ("write", "create", "delete", "export", "share"):
				self.assertFalse(frappe.has_permission(doc.doctype, ptype, doc.name), (doc.doctype, ptype))

		team = frappe.get_doc("Team", self.team.name)
		team.team_name = "Renamed by staff"
		with self.assertRaises(frappe.PermissionError):
			team.save()

	def test_staff_read_customer_data_fields_of_every_team(self):
		frappe.set_user(self.staff)

		team = frappe.get_doc("Team", self.team.name)
		team.apply_fieldlevel_read_permissions()
		self.assertEqual(team.owner_user, self.owner)
		self.assertEqual([member.user for member in team.members], [self.owner])

		rows = frappe.get_list("Team", filters={"name": self.team.name}, fields=["name", "owner_user"])
		self.assertEqual(rows, [{"name": self.team.name, "owner_user": self.owner}])

	def test_a_staff_viewer_manages_products_and_email_oauth_providers(self):
		frappe.set_user(self.staff)

		for doctype in ("Product", "Email OAuth Provider"):
			for ptype in ("read", "write", "create", "delete"):
				self.assertTrue(frappe.has_permission(doctype, ptype), (doctype, ptype))

		product = frappe.get_doc(
			{
				"doctype": "Product",
				"product_key": f"staff-{self.suffix}",
				"title": "Raven",
				"signup_app": "raven",
			}
		).insert()
		product.title = "Raven Chat"
		product.save()
		frappe.delete_doc("Product", product.name)
		self.assertFalse(frappe.db.exists("Product", product.name))

	def test_a_staff_viewer_previews_trial_images(self):
		product = frappe.get_doc(
			{
				"doctype": "Product",
				"product_key": f"staff-{self.suffix}",
				"title": "Raven",
				"signup_app": "raven",
			}
		).insert()
		frappe.set_user(self.staff)

		self.assertTrue(frappe.has_permission("Region", "select"))
		self.assertFalse(frappe.has_permission("Region", "read"))
		with (
			patch("central.site_provisioning.signup_offering", return_value="pilot"),
			patch("central.integrations.images.preview_images") as preview,
		):
			product.preview_images("par-2")
		preview.assert_called_once()

	def test_staff_read_no_operator_doctype(self):
		frappe.set_user(self.staff)

		for doctype in ("Invoice", "Payment Method", "Activity Event"):
			self.assertFalse(frappe.has_permission(doctype, "read"), doctype)

	def test_a_staff_viewer_gets_no_capability(self):
		self.assertFalse(can(self.staff, self.team.name, "server:view"))
		self.assertFalse(can(self.staff, self.team.name, "team:edit"))

	def test_a_member_still_reads_customer_data_fields(self):
		frappe.set_user(self.owner)

		team = frappe.get_doc("Team", self.team.name)
		team.apply_fieldlevel_read_permissions()
		self.assertEqual(team.owner_user, self.owner)
		self.assertTrue(team.members)

		rows = frappe.get_list(
			"Virtual Machine", filters={"team": self.team.name}, fields=["name", "firewall_rules"]
		)
		self.assertEqual(rows[0].firewall_rules, self.server.firewall_rules)

	def test_staff_keep_central_user(self):
		self.assertLessEqual(set(STAFF_ROLES), set(frappe.get_roles(self.staff)))
		self.assertEqual(frappe.db.get_value("User", self.staff, "user_type"), "System User")

	def test_the_staff_role_profile_holds_central_user(self):
		name = f"Frappe Employee {self.suffix}"
		with patch("central.users.STAFF_ROLE_PROFILE", name):
			ensure_staff_role_profile()

		profile = frappe.get_doc("Role Profile", name)
		self.assertEqual({row.role for row in profile.roles}, set(STAFF_ROLES))

	def _team(self):
		return frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": f"Staff Viewer {self.suffix}",
				"owner_user": self.owner,
				"members": [{"user": self.owner, "role": "Owner", "status": "Active"}],
			}
		).insert()

	def _server(self):
		return frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": f"staff-viewer-{self.suffix}",
				"team": self.team.name,
				"region": ensure_atlas_instance(f"staff-{self.suffix}"),
				"status": "Running",
				"firewall_rules": '[{"port": 22}]',
			}
		).insert(ignore_permissions=True)

	def _site(self):
		return frappe.get_doc(
			{
				"doctype": "Site",
				"site_name": f"staff-viewer-{self.suffix}.example.test",
				"team": self.team.name,
				"server": self.server.name,
			}
		).insert(ignore_permissions=True)
