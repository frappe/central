from unittest.mock import patch

import frappe
from frappe.desk.form.load import getdoc
from frappe.desk.reportview import execute as reportview_execute
from frappe.tests import IntegrationTestCase

from central.iam import can
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance


def ensure_staff_viewer(email: str) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Staff",
				"send_welcome_email": 0,
				"role_profiles": [{"role_profile": "Frappe Employee"}],
			}
		).insert()
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

	def test_a_staff_viewer_does_not_read_customer_data_fields(self):
		frappe.set_user(self.staff)

		team = frappe.get_doc("Team", self.team.name)
		team.apply_fieldlevel_read_permissions()
		self.assertEqual(team.team_name, self.team.team_name)
		self.assertIsNone(team.get("owner_user"))
		self.assertFalse(team.get("members"))

		server = frappe.get_doc("Virtual Machine", self.server.name)
		server.apply_fieldlevel_read_permissions()
		self.assertIsNone(server.get("firewall_rules"))

		rows = frappe.get_list("Team", filters={"name": self.team.name}, fields=["name", "owner_user"])
		self.assertEqual(rows, [{"name": self.team.name}])
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list("Team", filters={"owner_user": self.owner})

	def test_desk_form_and_list_hide_customer_data_fields(self):
		frappe.set_user(self.staff)

		getdoc("Team", self.team.name)
		form = frappe.response.docs[0].as_dict()
		self.assertEqual(form.team_name, self.team.team_name)
		self.assertIsNone(form.get("owner_user"))
		self.assertFalse(form.get("members"))

		rows = reportview_execute("Team", fields=["name", "owner_user"], filters={"name": self.team.name})
		self.assertEqual([row.get("owner_user") for row in rows], [None])

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

	def test_a_staff_viewer_reads_no_other_customer_doctype(self):
		frappe.set_user(self.staff)

		for doctype in ("Invoice", "Payment Method", "Team SSH Key", "Team Service", "Activity Event"):
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

	def test_a_new_staff_viewer_does_not_get_central_user(self):
		self.assertNotIn("Central User", frappe.get_roles(self.staff))
		self.assertEqual(frappe.db.get_value("User", self.staff, "user_type"), "System User")

	def test_a_user_cannot_be_both_staff_viewer_and_central_user(self):
		user = frappe.get_doc("User", self.owner)
		user.append("roles", {"role": "Staff Viewer"})
		with self.assertRaises(frappe.ValidationError):
			user.save()

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
