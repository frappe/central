import frappe
from frappe.tests import IntegrationTestCase

from central.api.identity import my_teams
from central.api.partners import describe_my_teams, get_team_partners
from central.iam import can, clear_grants_cache, is_active_team_member
from central.tests.test_iam import ensure_user
from central.tests.test_partner_setup import make_partner, make_team


class TestPartnerAccess(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.owner = ensure_user("access.partner.owner@example.test")
		self.staff = ensure_user("access.partner.staff@example.test")
		self.partner = make_partner("Access Partner", self.owner)
		self.partner_team = self.partner.team
		self.add_member(self.partner_team, self.staff, "Developer")

		self.client = make_team("Access Client", ensure_user("access.client@example.test"))
		self.link = frappe.get_doc(
			{
				"doctype": "Partner Client Link",
				"partner_team": self.partner_team,
				"client_team": self.client,
				"status": "Active",
				"partner_access": 1,
			}
		).insert()

	def add_member(self, team: str, user: str, role: str) -> None:
		doc = frappe.get_doc("Team", team)
		doc.append("members", {"user": user, "role": role, "status": "Active"})
		doc.save()

	def give_client_access(self, role: str | None, team_role: str = "Developer") -> None:
		frappe.set_user(self.owner)
		roles = [{"role": team_role}]
		if role:
			roles.append({"role": role, "resource_type": "Clients"})
		frappe.get_doc("Team", self.partner_team).set_member_roles(self.staff, roles)
		frappe.set_user("Administrator")

	def staff_can(self, capability: str) -> bool:
		clear_grants_cache()
		return can(self.staff, self.client, capability)

	def test_client_access_reaches_the_client_and_nothing_more(self):
		self.assertFalse(self.staff_can("server:view"))
		self.give_client_access("Developer")

		self.assertTrue(self.staff_can("server:create"))
		self.assertFalse(self.staff_can("billing:view"))
		self.assertFalse(self.staff_can("team:manage_members"))
		self.assertFalse(is_active_team_member(self.staff, self.client))

	def test_billing_is_managed_only_while_the_partner_pays(self):
		self.give_client_access("Billing")
		self.assertTrue(self.staff_can("billing:view"))
		self.assertFalse(self.staff_can("billing:manage"))

		self.link.db_set("paid_by_partner", 1)
		self.assertTrue(self.staff_can("billing:manage"))

	def test_access_stops_when_the_client_removes_it_or_the_link_ends(self):
		self.give_client_access("Developer")
		self.link.db_set("partner_access", 0)
		self.assertFalse(self.staff_can("server:view"))

		self.link.db_set({"partner_access": 1, "status": "Ended"})
		self.assertFalse(self.staff_can("server:view"))

	def test_a_custom_role_never_brings_team_capabilities_to_a_client(self):
		role = frappe.get_doc(
			{
				"doctype": "Team Role",
				"role_name": "Lead",
				"team": self.partner_team,
				"capabilities": [{"capability": "team:manage_members"}, {"capability": "server:power"}],
			}
		).insert()
		self.give_client_access(role.name)

		self.assertTrue(self.staff_can("server:power"))
		self.assertTrue(self.staff_can("server:view"))
		self.assertFalse(self.staff_can("team:manage_members"))

	def test_another_partners_staff_reach_nothing(self):
		other_owner = ensure_user("access.other.owner@example.test")
		other = make_partner("Access Other Partner", other_owner)
		doc = frappe.get_doc("Team", other.team)
		doc.append(
			"members",
			{"user": other_owner, "role": "Developer", "resource_type": "Clients", "status": "Active"},
		)
		doc.save()

		clear_grants_cache()
		self.assertFalse(can(other_owner, self.client, "server:view"))

	def test_a_role_on_the_partner_team_keeps_the_client_access_row(self):
		self.give_client_access("Developer", team_role="Developer")
		rows = frappe.get_all(
			"Team Member", filters={"parent": self.partner_team, "user": self.staff}, pluck="resource_type"
		)
		self.assertEqual(sorted(rows), ["*", "Clients"])

	def test_client_access_needs_a_partner_team_and_a_role_on_it(self):
		plain = make_team("Access Plain Co", self.owner, [(self.staff, "Developer")])
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Team", plain).set_member_roles(
				self.staff, [{"role": "Developer"}, {"role": "Developer", "resource_type": "Clients"}]
			)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Team", self.partner_team).set_member_roles(
				self.staff, [{"role": "Developer", "resource_type": "Clients"}]
			)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Team", self.partner_team).set_member_roles(self.staff, [{"role": "Partner"}])

	def test_the_client_appears_in_the_staff_members_team_list_only_through_the_partner(self):
		self.give_client_access("Viewer")
		frappe.set_user(self.staff)
		client = next(team for team in my_teams() if team["name"] == self.client)
		self.assertEqual(
			(client["role"], client["via_partner"], client["onboarding"]), ("Partner", "Access Partner", [])
		)
		self.assertNotIn(self.client, [team["name"] for team in describe_my_teams()])

	def test_client_access_is_not_a_role_on_the_partner_team_and_is_counted_for_the_client(self):
		self.give_client_access("Admin", team_role="Viewer")
		frappe.set_user(self.staff)
		partner = next(team for team in my_teams() if team["name"] == self.partner_team)
		self.assertEqual((partner["role"], partner["is_partner"]), ("Viewer", True))

		frappe.set_user("access.client@example.test")
		self.assertEqual(get_team_partners(team=self.client)["partner"]["staff_count"], 1)
		self.link.db_set("partner_access", 0)
		self.assertEqual(get_team_partners(team=self.client)["partner"]["staff_count"], 0)
