import frappe
from frappe.tests import IntegrationTestCase

from central.api import fc_teams
from central.iam import can, get_effective_permissions, get_fc_teams_claim
from central.oauth import install_oauth_claim_patch


def ensure_user(email: str) -> str:
	if frappe.db.exists("User", email):
		return email

	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@", 1)[0],
			"enabled": 1,
			"send_welcome_email": 0,
			"roles": [{"role": "Central User"}],
		}
	)
	user.insert()
	return email


class TestCentralIAM(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("iam.owner@example.test")
		self.viewer = ensure_user("iam.viewer@example.test")
		self.developer = ensure_user("iam.developer@example.test")

	def make_team(self, team_name: str, user: str, role: str):
		team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": team_name,
				"owner_user": self.owner,
				"members": [
					{"user": self.owner, "role": "Owner", "status": "Active"},
					{"user": user, "role": role, "status": "Active"},
				],
			}
		)
		team.insert()
		return team

	def test_fixtures_create_capability_catalog_and_system_roles(self):
		# 29 capabilities across three planes: central (6), atlas (10), bench (13).
		self.assertEqual(frappe.db.count("Capability"), 29)
		self.assertEqual(frappe.db.count("Capability", {"plane": "bench"}), 13)
		self.assertEqual(frappe.db.count("Capability", {"plane": "atlas"}), 10)

		owner_caps = set(frappe.get_all("Role Capability", {"parent": "Owner"}, pluck="capability"))
		admin_caps = set(frappe.get_all("Role Capability", {"parent": "Admin"}, pluck="capability"))
		developer_caps = set(frappe.get_all("Role Capability", {"parent": "Developer"}, pluck="capability"))
		viewer_caps = set(frappe.get_all("Role Capability", {"parent": "Viewer"}, pluck="capability"))
		billing_caps = set(frappe.get_all("Role Capability", {"parent": "Billing"}, pluck="capability"))

		for caps in (owner_caps, admin_caps, developer_caps):
			self.assertIn("vm:snapshot", caps)
			self.assertIn("vm:rebuild", caps)
		# Bench plane: Owner/Admin manage the bench; Developer operates sites but
		# can't create/drop them; Viewer is read-only.
		self.assertIn("site:create", owner_caps)
		self.assertIn("site:create", admin_caps)
		self.assertNotIn("site:create", developer_caps)
		self.assertIn("site:migrate", developer_caps)
		self.assertEqual(viewer_caps, {"asset:view", "cluster:view", "log:view", "site:view", "vm:view"})
		self.assertNotIn("vm:snapshot", billing_caps)
		self.assertNotIn("vm:rebuild", billing_caps)

		# Journey cap ladder (#22): cluster:view → vm:view → vm:open. Everyone who
		# sees VMs sees their cluster; only Owner/Admin/Developer may open a bench.
		for caps in (owner_caps, admin_caps, developer_caps, viewer_caps, billing_caps):
			self.assertIn("cluster:view", caps)
		for caps in (owner_caps, admin_caps, developer_caps):
			self.assertIn("vm:open", caps)
		for caps in (viewer_caps, billing_caps):
			self.assertNotIn("vm:open", caps)

	def test_user_claim_is_team_scoped(self):
		team_a = self.make_team("IAM Team A", self.viewer, "Viewer")
		team_b = self.make_team("IAM Team B", self.developer, "Developer")

		viewer_claim = get_fc_teams_claim(self.viewer)

		self.assertIn(team_a.name, viewer_claim)
		self.assertNotIn(team_b.name, viewer_claim)
		self.assertTrue(can(self.viewer, team_a.name, "vm:view"))
		self.assertFalse(can(self.viewer, team_a.name, "vm:terminate"))

	def test_developer_can_terminate_but_not_manage_billing(self):
		team = self.make_team("IAM Dev Team", self.developer, "Developer")

		self.assertTrue(can(self.developer, team.name, "vm:terminate"))
		self.assertFalse(can(self.developer, team.name, "billing:manage"))

	def test_effective_permissions_shape_matches_fc_teams_claim(self):
		team = self.make_team("IAM Effective Team", self.viewer, "Viewer")

		effective = get_effective_permissions(self.viewer, team.name)

		self.assertEqual(effective["user"], self.viewer)
		self.assertEqual(
			effective["teams"][team.name]["caps"],
			["asset:view", "cluster:view", "log:view", "site:view", "vm:view"],
		)
		self.assertEqual(effective["teams"][team.name]["grants"][0]["source"], "member")

	def test_permission_probe_evaluates_on_save(self):
		team = self.make_team("IAM Probe Team", self.viewer, "Viewer")
		probe = frappe.get_doc(
			{
				"doctype": "IAM Permission Probe",
				"user": self.viewer,
				"team": team.name,
				"capability": "vm:terminate",
			}
		)
		probe.insert()

		self.assertFalse(probe.allowed)
		self.assertIn(team.name, probe.resolved_grants)

	def test_oauth_userinfo_patch_adds_fc_teams(self):
		team = self.make_team("IAM OAuth Team", self.viewer, "Viewer")
		install_oauth_claim_patch()

		import frappe.oauth as frappe_oauth

		userinfo = frappe_oauth.get_userinfo(frappe.get_doc("User", self.viewer))

		self.assertIn("fc_teams", userinfo)
		self.assertIn(team.name, userinfo["fc_teams"])

	def test_new_user_gets_default_owner_team(self):
		email = f"iam.signup.{frappe.generate_hash(length=8)}@example.test"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "IAM Signup",
				"enabled": 1,
				"send_welcome_email": 0,
			}
		)
		user.insert()

		user.reload()
		teams = frappe.get_all(
			"Team",
			filters={"owner_user": email},
			fields=["name", "team_name", "status"],
			order_by="creation asc",
		)

		self.assertIn("Central User", {row.role for row in user.roles})
		self.assertEqual(len(teams), 1)
		self.assertEqual(teams[0].status, "Active")

		team = frappe.get_doc("Team", teams[0].name)
		self.assertEqual(len(team.members), 1)
		self.assertEqual(team.members[0].user, email)
		self.assertEqual(team.members[0].role, "Owner")
		self.assertEqual(team.members[0].status, "Active")

		claim = get_fc_teams_claim(email)
		self.assertIn(team.name, claim)
		self.assertTrue(can(email, team.name, "team:manage_members"))
		self.assertTrue(can(email, team.name, "vm:terminate"))

	def test_central_user_cannot_inspect_another_users_fc_teams(self):
		frappe.set_user(self.viewer)
		try:
			with self.assertRaises(frappe.PermissionError):
				fc_teams(self.developer)
		finally:
			frappe.set_user("Administrator")
