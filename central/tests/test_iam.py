import frappe
from frappe.tests import IntegrationTestCase

from central.iam import (
	can,
	expand_capabilities,
	get_effective_permissions,
	get_fc_teams_claim,
	resolve_resource_scope,
)
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
		# 15 capabilities across two live planes: central (7) + atlas (8). v3 makes
		# server the atomic unit — the bench plane and asset:view are dropped.
		self.assertEqual(frappe.db.count("Capability"), 15)
		self.assertEqual(frappe.db.count("Capability", {"plane": "central"}), 7)
		self.assertEqual(frappe.db.count("Capability", {"plane": "atlas"}), 8)
		self.assertEqual(frappe.db.count("Capability", {"plane": "bench"}), 0)
		# The retired roles are gone; the five-rung ladder is all that remains.
		self.assertEqual(frappe.db.count("Team Role", {"is_system": 1}), 5)
		for retired in ("Operator", "Site Manager", "Support"):
			self.assertFalse(frappe.db.exists("Team Role", retired))

		owner_caps = set(frappe.get_all("Role Capability", {"parent": "Owner"}, pluck="capability"))
		admin_caps = set(frappe.get_all("Role Capability", {"parent": "Admin"}, pluck="capability"))
		developer_caps = set(frappe.get_all("Role Capability", {"parent": "Developer"}, pluck="capability"))
		viewer_caps = set(frappe.get_all("Role Capability", {"parent": "Viewer"}, pluck="capability"))
		billing_caps = set(frappe.get_all("Role Capability", {"parent": "Billing"}, pluck="capability"))

		# Full server lifecycle is shared by Owner, Admin, and Developer.
		for caps in (owner_caps, admin_caps, developer_caps):
			for cap in (
				"server:create",
				"server:power",
				"server:resize",
				"server:snapshot",
				"server:terminate",
				"server:open",
			):
				self.assertIn(cap, caps)
		# Team management is Owner/Admin; deleting the team is Owner-only.
		for caps in (owner_caps, admin_caps):
			self.assertIn("team:manage_members", caps)
		self.assertNotIn("team:manage_members", developer_caps)
		self.assertIn("team:delete", owner_caps)
		self.assertNotIn("team:delete", admin_caps)
		# Billing is day-to-day team administration, so Owner/Admin/Billing carry it.
		for cap in ("billing:view", "billing:manage"):
			self.assertIn(cap, owner_caps)
			self.assertIn(cap, admin_caps)
			self.assertIn(cap, billing_caps)
			self.assertNotIn(cap, developer_caps)
		# Viewer can read services; Billing can configure them as well.
		self.assertEqual(viewer_caps, {"cluster:view", "server:view", "service:view"})
		self.assertEqual(
			billing_caps,
			{
				"billing:view",
				"billing:manage",
				"cluster:view",
				"server:view",
				"service:view",
				"service:manage",
			},
		)

		# server:open is the console gate; the read-only Viewer and Billing lack it.
		for caps in (owner_caps, admin_caps, developer_caps):
			self.assertIn("server:open", caps)
		for caps in (viewer_caps, billing_caps):
			self.assertNotIn("server:open", caps)

		# Every system role can still see servers and the cluster they live in.
		for caps in (owner_caps, admin_caps, developer_caps, viewer_caps, billing_caps):
			self.assertIn("cluster:view", caps)
			self.assertIn("server:view", caps)

	def test_capability_implications_close_a_grant(self):
		# server:create can't stand alone — it pulls in the server:view + cluster:view
		# needed to use it.
		expanded = set(expand_capabilities(["server:create"]))
		self.assertEqual(expanded, {"server:create", "server:view", "cluster:view"})

		self.assertIn("server:view", expand_capabilities(["server:open"]))

		# Already-closed sets are returned unchanged (order preserved, no dupes).
		closed = ["server:view", "cluster:view"]
		self.assertEqual(expand_capabilities(closed), closed)

	def test_user_claim_is_team_scoped(self):
		team_a = self.make_team("IAM Team A", self.viewer, "Viewer")
		team_b = self.make_team("IAM Team B", self.developer, "Developer")

		viewer_claim = get_fc_teams_claim(self.viewer)

		self.assertIn(team_a.name, viewer_claim)
		self.assertNotIn(team_b.name, viewer_claim)
		self.assertTrue(can(self.viewer, team_a.name, "server:view"))
		self.assertFalse(can(self.viewer, team_a.name, "server:terminate"))

	def test_developer_operates_servers_but_not_team_or_billing(self):
		team = self.make_team("IAM Dev Team", self.developer, "Developer")

		self.assertTrue(can(self.developer, team.name, "server:create"))
		self.assertTrue(can(self.developer, team.name, "server:terminate"))
		self.assertFalse(can(self.developer, team.name, "team:manage_members"))
		self.assertFalse(can(self.developer, team.name, "billing:manage"))

	def test_effective_permissions_shape_matches_fc_teams_claim(self):
		team = self.make_team("IAM Effective Team", self.viewer, "Viewer")

		effective = get_effective_permissions(self.viewer, team.name)

		self.assertEqual(effective["user"], self.viewer)
		self.assertEqual(
			effective["teams"][team.name]["caps"],
			["cluster:view", "server:view", "service:view"],
		)
		self.assertEqual(effective["teams"][team.name]["grants"][0]["source"], "member")

	def test_permission_probe_evaluates_on_save(self):
		team = self.make_team("IAM Probe Team", self.viewer, "Viewer")
		probe = frappe.get_doc(
			{
				"doctype": "IAM Permission Probe",
				"user": self.viewer,
				"team": team.name,
				"capability": "server:terminate",
			}
		)
		probe.insert()

		self.assertFalse(probe.allowed)
		self.assertIn(team.name, probe.resolved_grants)

	def test_scoped_grant_narrows_can_to_its_resource(self):
		# A Developer scoped to one server acts on that server only.
		team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "IAM Scoped Team",
				"owner_user": self.owner,
				"members": [
					{"user": self.owner, "role": "Owner", "status": "Active"},
					{
						"user": self.developer,
						"role": "Developer",
						"resource_type": "Server",
						"resource_name": "srv-x",
						"status": "Active",
					},
				],
			}
		).insert()

		# The named resource matches → allowed; a different server → denied.
		self.assertTrue(can(self.developer, team.name, "server:power", "Server", "srv-x"))
		self.assertFalse(can(self.developer, team.name, "server:power", "Server", "srv-y"))
		# A Server-scoped grant does not cover a Site of the same name.
		self.assertFalse(can(self.developer, team.name, "server:view", "Site", "srv-x"))
		# No resource named is the team-level/list question — the cap is held somewhere.
		self.assertTrue(can(self.developer, team.name, "server:power"))
		# The all-resources Owner grant covers any server.
		self.assertTrue(can(self.owner, team.name, "server:power", "Server", "srv-y"))

	def test_different_roles_on_different_servers(self):
		# The headline case: one member, two servers, a different role on each.
		team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "IAM Mixed Scope Team",
				"owner_user": self.owner,
				"members": [
					{"user": self.owner, "role": "Owner", "status": "Active"},
					{
						"user": self.developer,
						"role": "Developer",
						"resource_type": "Server",
						"resource_name": "srv-x",
						"status": "Active",
					},
					{
						"user": self.developer,
						"role": "Viewer",
						"resource_type": "Server",
						"resource_name": "srv-y",
						"status": "Active",
					},
				],
			}
		).insert()

		# Developer on srv-x → full lifecycle there; Viewer on srv-y → read-only there.
		self.assertTrue(can(self.developer, team.name, "server:power", "Server", "srv-x"))
		self.assertTrue(can(self.developer, team.name, "server:terminate", "Server", "srv-x"))
		self.assertFalse(can(self.developer, team.name, "server:power", "Server", "srv-y"))
		self.assertFalse(can(self.developer, team.name, "server:terminate", "Server", "srv-y"))
		# But both are visible — the list shows exactly these two, nothing else.
		self.assertTrue(can(self.developer, team.name, "server:view", "Server", "srv-x"))
		self.assertTrue(can(self.developer, team.name, "server:view", "Server", "srv-y"))
		self.assertFalse(can(self.developer, team.name, "server:view", "Server", "srv-z"))
		self.assertEqual(
			resolve_resource_scope(self.developer, "server:view", "Server").get(team.name),
			{"srv-x", "srv-y"},
		)

	def test_resolve_resource_scope_maps_teams_to_allowed_names(self):
		team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "IAM Scope Map Team",
				"owner_user": self.owner,
				"members": [
					{"user": self.owner, "role": "Owner", "status": "Active"},
					{
						"user": self.developer,
						"role": "Developer",
						"resource_type": "Server",
						"resource_name": "srv-x",
						"status": "Active",
					},
				],
			}
		).insert()

		self.assertEqual(
			resolve_resource_scope(self.developer, "server:view", "Server").get(team.name),
			{"srv-x"},
		)
		# No Site-scoped grant → the team is absent from the Site scope entirely.
		self.assertNotIn(team.name, resolve_resource_scope(self.developer, "server:view", "Site"))
		# The Owner's all-resources grant resolves to the wildcard.
		self.assertEqual(resolve_resource_scope(self.owner, "server:view", "Server").get(team.name), "*")

	def test_scoped_grant_leaves_fc_teams_claim_backward_compatible(self):
		# The bench contract isn't scope-aware yet, so the claim stays one entry per
		# role with scope "*" (spec/ATLAS_COORDINATION.md).
		team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "IAM Claim Compat Team",
				"owner_user": self.owner,
				"members": [
					{"user": self.owner, "role": "Owner", "status": "Active"},
					{
						"user": self.developer,
						"role": "Developer",
						"resource_type": "Server",
						"resource_name": "srv-x",
						"status": "Active",
					},
				],
			}
		).insert()

		entries = get_fc_teams_claim(self.developer)[team.name]
		self.assertTrue(all(entry["scope"] == "*" for entry in entries))
		developer_entry = next(entry for entry in entries if entry["role"] == "Developer")
		self.assertIn("server:power", developer_entry["caps"])

	def test_asset_has_permission_respects_scope(self):
		from central.permissions import asset_has_permission

		team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "IAM Asset Perm Team",
				"owner_user": self.owner,
				"members": [
					{"user": self.owner, "role": "Owner", "status": "Active"},
					{
						"user": self.developer,
						"role": "Developer",
						"resource_type": "Server",
						"resource_name": "srv-x",
						"status": "Active",
					},
				],
			}
		).insert()

		in_scope = frappe._dict(name="srv-x", team=team.name)
		out_of_scope = frappe._dict(name="srv-y", team=team.name)
		self.assertTrue(asset_has_permission(in_scope, self.developer, "read"))
		self.assertFalse(asset_has_permission(out_of_scope, self.developer, "read"))
		# The Owner's all-resources grant sees both.
		self.assertTrue(asset_has_permission(out_of_scope, self.owner, "read"))

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
		self.assertEqual(user.user_type, "Website User")
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
		self.assertTrue(can(email, team.name, "server:terminate"))
