from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import get_first_day, getdate

from central.api.identity import my_teams
from central.api.partners import (
	add_partner,
	end_partner_link,
	get_team_customers,
	set_partner_payer,
	set_partner_role,
)
from central.api.teams import list_team_members
from central.iam import PARTNER_BLOCKED_CAPABILITIES, can, get_partner_team_of
from central.tests.test_team_management import create_user


class TestPartnerAccess(IntegrationTestCase):
	"""Partner staff act on a customer team through an Active Partner Link, with its role."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.dispatch = patch("central.notification.engine.dispatch").start()
		self.addCleanup(patch.stopall)
		suffix = frappe.generate_hash(length=6)
		self.customer_owner = create_user(f"access.customer.{suffix}@example.test")
		self.partner_owner = create_user(f"access.partner.{suffix}@example.test")
		self.staff = create_user(f"access.staff.{suffix}@example.test")
		self.viewer_staff = create_user(f"access.viewer.{suffix}@example.test")

		self.customer_team = self._create_team("Northwind", self.customer_owner)
		self.partner_team = self._create_team(
			"Tridots", self.partner_owner, {self.staff: "Developer", self.viewer_staff: "Viewer"}
		)
		self.code = self._make_partner(self.partner_team)
		frappe.set_user(self.customer_owner)
		self.link = add_partner(self.customer_team, self.code)["name"]

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_new_link_gives_the_partner_viewer_access(self):
		self.assertEqual(frappe.db.get_value("Partner Link", self.link, "role"), "Viewer")
		self.assertTrue(can(self.staff, self.customer_team, "server:view"))
		self.assertFalse(can(self.staff, self.customer_team, "server:create"))

	def test_developer_access_never_holds_a_blocked_capability(self):
		frappe.set_user(self.customer_owner)
		set_partner_role(self.link, "Developer")

		self.assertTrue(can(self.staff, self.customer_team, "server:create"))
		self.assertTrue(can(self.staff, self.customer_team, "server:terminate"))
		for capability in PARTNER_BLOCKED_CAPABILITIES:
			self.assertFalse(can(self.staff, self.customer_team, capability), capability)

	def test_staff_without_the_partner_capability_get_nothing(self):
		self.assertFalse(can(self.viewer_staff, self.customer_team, "server:view"))
		self.assertNotIn(self.customer_team, [team["name"] for team in self._teams_of(self.viewer_staff)])

	def test_only_the_customer_chooses_viewer_or_developer(self):
		frappe.set_user(self.partner_owner)
		with self.assertRaises(frappe.PermissionError):
			set_partner_role(self.link, "Developer")

		frappe.set_user(self.customer_owner)
		for role in ("Owner", "Admin", "Billing"):
			with self.assertRaises(frappe.ValidationError):
				set_partner_role(self.link, role)

	def test_ending_the_link_stops_access_on_the_next_check(self):
		frappe.set_user(self.partner_owner)
		end_partner_link(self.link, "Contract ended")
		frappe.local.request_cache.clear()
		self.assertEqual(
			[(call.args[0], call.args[1]) for call in self.dispatch.call_args_list],
			[(self.customer_team, "partner_link_ended"), (self.partner_team, "partner_link_ended")],
		)

		self.assertFalse(can(self.staff, self.customer_team, "server:view"))
		self.assertNotIn(self.customer_team, [team["name"] for team in self._teams_of(self.staff)])

	def test_a_partner_cannot_reach_the_customers_of_its_customer(self):
		frappe.set_user(self.customer_owner)
		set_partner_role(self.link, "Developer")
		customer_code = self._make_partner(self.customer_team)
		second_owner = create_user(f"access.second.{frappe.generate_hash(length=6)}@example.test")
		second_team = self._create_team("Contoso", second_owner)
		frappe.set_user(second_owner)
		set_partner_role(add_partner(second_team, customer_code)["name"], "Developer")

		self.assertFalse(can(self.staff, second_team, "server:view"))

	def test_partner_staff_are_not_members(self):
		frappe.set_user(self.staff)
		with self.assertRaises(frappe.PermissionError):
			list_team_members(self.customer_team)

	def test_the_switcher_lists_the_customer_with_the_partner(self):
		team = next(team for team in self._teams_of(self.staff) if team["name"] == self.customer_team)
		self.assertEqual((team["via_partner"], team["role"]), ("Tridots", "Viewer"))

	def test_an_action_by_partner_staff_names_the_partner(self):
		self.assertEqual(get_partner_team_of(self.staff, self.customer_team), self.partner_team)
		self.assertIsNone(get_partner_team_of(self.customer_owner, self.customer_team))

	def test_removing_a_partner_from_the_program_ends_its_links(self):
		frappe.set_user("Administrator")
		frappe.get_doc("Team", self.partner_team).remove_from_partner_program("Left the program")

		self.assertEqual(frappe.db.get_value("Partner Link", self.link, "status"), "Ended")
		self.assertEqual(
			frappe.db.get_value("Team", self.partner_team, ["connect_partner_id", "partner_code"]),
			(None, None),
		)

	def test_partner_staff_see_customers_but_only_managers_accept_paying(self):
		frappe.set_user(self.staff)
		(row,) = get_team_customers(self.partner_team)["customers"]
		self.assertTrue(row["can_open"])
		self.assertEqual((row["mrr"], row["server_count"]), (0.0, 0))

		frappe.set_user(self.customer_owner)
		self.assertEqual(set_partner_payer(self.link, "Partner Requested")["payer"], "Partner Requested")
		frappe.set_user(self.staff)
		with self.assertRaises(frappe.PermissionError):
			set_partner_payer(self.link, "Partner")
		frappe.set_user(self.partner_owner)
		self.assertEqual(set_partner_payer(self.link, "Partner")["payer"], "Partner")

		frappe.set_user(self.viewer_staff)
		with self.assertRaises(frappe.PermissionError):
			get_team_customers(self.partner_team)

	def test_the_customer_team_shows_the_partner_that_pays(self):
		frappe.db.set_value(
			"Partner Link", self.link, {"payer": "Partner", "partner_pays_from": get_first_day(getdate())}
		)
		team = next(
			team for team in self._teams_of(self.customer_owner) if team["name"] == self.customer_team
		)
		self.assertEqual(team["paid_by"], "Tridots")

	def _teams_of(self, user: str) -> list[dict]:
		frappe.set_user(user)
		return my_teams()

	def _make_partner(self, team: str) -> str:
		frappe.set_user("Administrator")
		doc = frappe.get_doc("Team", team)
		doc.connect_partner_id = f"PARTNER-{frappe.generate_hash(length=8)}"
		doc.save()
		return doc.partner_code

	def _create_team(self, team_name: str, owner: str, members: dict[str, str] | None = None) -> str:
		frappe.set_user("Administrator")
		rows = [{"user": owner, "role": "Owner", "status": "Active"}]
		rows += [{"user": user, "role": role, "status": "Active"} for user, role in (members or {}).items()]
		return (
			frappe.get_doc({"doctype": "Team", "team_name": team_name, "owner_user": owner, "members": rows})
			.insert()
			.name
		)
