from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api import connect
from central.api.identity import my_teams
from central.api.partners import (
	add_partner,
	end_partner_link,
	get_partner_by_code,
	get_team_customers,
	get_team_partner,
)
from central.errors import PartnersDisabledError
from central.tests.test_team_management import create_user
from central.tests.utils import central_limit, ensure_server


class TestPartnerLinks(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.enterContext(central_limit("enable_partners", 1))
		self.dispatch = patch("central.notification.engine.dispatch").start()
		self.addCleanup(patch.stopall)
		suffix = frappe.generate_hash(length=6)
		self.customer_owner = create_user(f"customer.owner.{suffix}@example.test")
		self.developer = create_user(f"customer.developer.{suffix}@example.test")
		self.partner_owner = create_user(f"partner.owner.{suffix}@example.test")
		self.stranger = create_user(f"stranger.{suffix}@example.test")
		self.integration = create_user("connect.integration@example.test")
		if "Connect Integration" not in frappe.get_roles(self.integration):
			frappe.get_doc("User", self.integration).add_roles("Connect Integration")

		self.customer_team = self._create_team(
			"Northwind", self.customer_owner, {self.developer: "Developer"}
		)
		self.partner_id = f"PARTNER-{suffix}"
		self.partner_team = self._create_team("Tridots", self.partner_owner)
		team = frappe.get_doc("Team", self.partner_team)
		team.connect_partner_id = self.partner_id
		team.save()
		self.code = team.partner_code
		self.stranger_team = self._create_team("Stranger", self.stranger)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_customer_adds_the_partner_by_code(self):
		frappe.set_user(self.customer_owner)
		self.assertEqual(get_partner_by_code(self.customer_team, self.code)["partner_name"], "Tridots")

		link = add_partner(self.customer_team, self.code.lower(), " PCUST-00012 ")
		self.assertEqual((link["status"], link["partner_team"]), ("Active", self.partner_team))
		self.assertEqual(frappe.db.get_value("Partner Link", link["name"], "reference"), "PCUST-00012")
		self.assertEqual(get_team_partner(self.customer_team)["name"], link["name"])
		team = next(team for team in my_teams() if team["name"] == self.customer_team)
		self.assertTrue(team["has_partner"])

		frappe.set_user(self.partner_owner)
		customers = get_team_customers(self.partner_team)
		self.assertEqual(customers["partner_code"], self.code)
		self.assertEqual([row["customer_team"] for row in customers["customers"]], [self.customer_team])

	def test_an_unknown_code_is_refused(self):
		frappe.set_user(self.customer_owner)
		with self.assertRaises(frappe.DoesNotExistError):
			add_partner(self.customer_team, "NOP-00000")

	def test_only_a_partner_manager_of_the_team_adds_a_partner(self):
		frappe.set_user(self.developer)
		with self.assertRaises(frappe.PermissionError):
			add_partner(self.customer_team, self.code)

		frappe.set_user(self.stranger)
		with self.assertRaises(frappe.PermissionError):
			add_partner(self.customer_team, self.code)

	def test_a_link_is_created_only_with_the_code(self):
		frappe.set_user(self.customer_owner)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "Partner Link",
					"customer_team": self.customer_team,
					"partner_team": self.partner_team,
				}
			).insert()

	def test_a_team_has_one_partner_and_cannot_partner_itself(self):
		frappe.set_user(self.customer_owner)
		add_partner(self.customer_team, self.code)
		with self.assertRaises(frappe.ValidationError):
			add_partner(self.customer_team, self.code)

		frappe.set_user(self.partner_owner)
		with self.assertRaises(frappe.ValidationError):
			add_partner(self.partner_team, self.code)

	def test_partners_off_refuses_a_new_link_but_keeps_the_active_one(self):
		frappe.set_user(self.customer_owner)
		add_partner(self.customer_team, self.code)

		with central_limit("enable_partners", 0):
			self.assertEqual(get_team_partner(self.customer_team)["status"], "Active")
			frappe.set_user(self.stranger)
			with self.assertRaises(PartnersDisabledError):
				add_partner(self.stranger_team, self.code)

	def test_a_partner_team_cannot_add_a_partner(self):
		frappe.set_user("Administrator")
		other = frappe.get_doc("Team", self.stranger_team)
		other.connect_partner_id = f"OTHER-{frappe.generate_hash(length=6)}"
		other.save()

		frappe.set_user(self.partner_owner)
		with self.assertRaisesRegex(frappe.ValidationError, "partner team cannot add"):
			add_partner(self.partner_team, other.partner_code)

	def test_only_the_two_teams_see_the_link(self):
		frappe.set_user(self.customer_owner)
		name = add_partner(self.customer_team, self.code)["name"]

		for user, visible in (
			(self.customer_owner, True),
			(self.partner_owner, True),
			(self.developer, False),
			(self.stranger, False),
		):
			frappe.set_user(user)
			self.assertEqual(bool(frappe.get_list("Partner Link", filters={"name": name})), visible, user)
			self.assertEqual(frappe.has_permission("Partner Link", "read", name), visible, user)

	def test_either_side_ends_the_link_and_an_ended_link_stays_ended(self):
		frappe.set_user(self.customer_owner)
		name = add_partner(self.customer_team, self.code)["name"]

		frappe.set_user(self.stranger)
		with self.assertRaises(frappe.PermissionError):
			end_partner_link(name, "Not mine")

		frappe.set_user(self.partner_owner)
		self.assertEqual(end_partner_link(name, "Contract ended")["status"], "Ended")
		self.assertIsNone(get_team_partner_as(self.customer_owner, self.customer_team))

		frappe.set_user(self.stranger)
		with self.assertRaises(frappe.PermissionError):
			end_partner_link(name, "Read an ended link")

		frappe.set_user(self.customer_owner)
		link = frappe.get_doc("Partner Link", name)
		link.status = "Active"
		with self.assertRaises(frappe.ValidationError):
			link.save()
		self.assertNotEqual(add_partner(self.customer_team, self.code)["name"], name)

	def test_a_manager_cannot_edit_the_link_by_hand(self):
		frappe.set_user(self.customer_owner)
		link = frappe.get_doc("Partner Link", add_partner(self.customer_team, self.code)["name"])
		link.reference = "PCUST-forged"
		with self.assertRaises(frappe.PermissionError):
			link.save()

	def test_connect_reads_and_ends_the_partners_links(self):
		frappe.set_user(self.customer_owner)
		name = add_partner(self.customer_team, self.code, "PCUST-00012")["name"]

		frappe.set_user(self.customer_owner)
		with self.assertRaises(frappe.PermissionError):
			connect.get_partner_customers(self.partner_id)

		frappe.set_user("Administrator")
		server = ensure_server(f"vm-{frappe.generate_hash(length=6)}", self.customer_team, title="erp-1")

		frappe.set_user(self.integration)
		(row,) = connect.get_partner_customers(self.partner_id)
		self.assertEqual(
			(row["link"], row["reference"], row["customer_team_name"], row["customer_email"], row["role"]),
			(name, "PCUST-00012", "Northwind", self.customer_owner, "Viewer"),
		)
		self.assertEqual((row["mrr"], row["currency"]), (0.0, "INR"))
		self.assertEqual(
			[(item["name"], item["status"], item["amount"], item["sites"]) for item in row["servers"]],
			[("erp-1", "Running", 0.0, [])],
		)
		self.assertNotIn(server, str(row["servers"]))
		with self.assertRaises(frappe.ValidationError):
			connect.get_partner_customers("PARTNER-unknown")

		self.assertEqual(connect.end_partner_link(name, "Churned on Connect"), {"status": "Ended"})
		self.assertEqual(connect.end_partner_link(name, "Again"), {"status": "Ended"})
		self.assertEqual(frappe.db.get_value("Partner Link", name, "end_reason"), "Churned on Connect")

	def _create_team(self, team_name: str, owner: str, members: dict[str, str] | None = None) -> str:
		frappe.set_user("Administrator")
		rows = [{"user": owner, "role": "Owner", "status": "Active"}]
		rows += [{"user": user, "role": role, "status": "Active"} for user, role in (members or {}).items()]
		return (
			frappe.get_doc({"doctype": "Team", "team_name": team_name, "owner_user": owner, "members": rows})
			.insert()
			.name
		)


def get_team_partner_as(user: str, team: str) -> dict | None:
	frappe.set_user(user)
	return get_team_partner(team)
