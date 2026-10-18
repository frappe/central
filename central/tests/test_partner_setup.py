import hashlib

import frappe
from frappe.tests import IntegrationTestCase

from central.api.partners import get_partner_for_link, my_teams_for_partner, request_partner_link
from central.central.doctype.partner_profile.partner_profile import hash_partner_code
from central.tests.test_iam import ensure_user


def make_team(team_name: str, owner: str, members: list[tuple[str, str]] = ()) -> str:
	team = frappe.get_doc(
		{
			"doctype": "Team",
			"team_name": team_name,
			"owner_user": owner,
			"members": [
				{"user": owner, "role": "Owner", "status": "Active"},
				*({"user": user, "role": role, "status": "Active"} for user, role in members),
			],
		}
	)
	team.insert()
	return team.name


def make_partner(team_name: str, owner: str):
	team = make_team(team_name, owner)
	return frappe.get_doc({"doctype": "Partner Profile", "team": team}).insert()


class TestPartnerProfile(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.partner = make_partner("Setup Partner", ensure_user("setup.partner@example.test"))

	def test_the_code_is_made_like_frappe_clouds_partner_referral_code(self):
		self.assertRegex(self.partner.partner_code, r"^[A-Z0-9]{10}$")

	def test_the_hash_is_sha256_of_the_code(self):
		self.assertEqual(
			self.partner.partner_code_hash, hashlib.sha256(self.partner.partner_code.encode()).hexdigest()
		)

	def test_the_hash_ignores_spaces_around_the_code(self):
		self.assertEqual(hash_partner_code(f" {self.partner.partner_code} "), self.partner.partner_code_hash)

	def test_central_users_cant_read_partner_codes_through_the_rest_api(self):
		frappe.set_user(ensure_user("setup.customer@example.test"))
		self.addCleanup(frappe.set_user, "Administrator")
		self.assertFalse(frappe.has_permission("Partner Profile", "read"))


class TestPartnerSetupLink(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.partner = make_partner("Link Partner", ensure_user("link.partner@example.test"))
		self.p = self.partner.partner_code_hash

	def test_a_link_names_its_partner_by_name_and_logo_only(self):
		self.assertEqual(get_partner_for_link(self.p), {"name": "Link Partner", "logo": None})

	def test_an_unknown_or_malformed_hash_finds_no_partner(self):
		self.assertIsNone(get_partner_for_link("0" * 64))
		self.assertIsNone(get_partner_for_link(self.partner.partner_code))
		self.assertIsNone(get_partner_for_link(""))


class TestTeamsForPartner(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.partner = make_partner("Pick Partner", ensure_user("pick.partner@example.test"))
		self.other_partner = make_partner("Other Partner", ensure_user("pick.other@example.test"))
		self.customer = ensure_user("pick.customer@example.test")
		self.boss = ensure_user("pick.boss@example.test")

		self.own = make_team("Own Co", self.customer)
		self.with_other = make_team("Linked Co", self.customer)
		frappe.get_doc(
			{
				"doctype": "Partner Client Link",
				"partner_team": self.other_partner.team,
				"client_team": self.with_other,
				"status": "Active",
			}
		).insert()
		self.as_developer = make_team("Boss Co", self.boss, [(self.customer, "Developer")])

		frappe.set_user(self.customer)
		self.addCleanup(frappe.set_user, "Administrator")
		self.teams = {team["name"]: team for team in my_teams_for_partner(self.partner.partner_code_hash)}

	def test_a_team_the_user_owns_can_be_picked(self):
		self.assertTrue(self.teams[self.own]["available"])
		self.assertIsNone(self.teams[self.own]["reason"])

	def test_a_team_with_another_partner_cant_be_picked(self):
		team = self.teams[self.with_other]
		self.assertEqual((team["available"], team["reason"]), (False, "linked_to_another_partner"))
		self.assertEqual(team["current_partner"], "Other Partner")

	def test_a_team_the_user_cant_manage_billing_for_cant_be_picked(self):
		team = self.teams[self.as_developer]
		self.assertEqual((team["available"], team["reason"]), (False, "cannot_manage"))


class TestRequestPartnerLink(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.partner = make_partner("Request Partner", ensure_user("request.partner@example.test"))
		self.p = self.partner.partner_code_hash
		self.customer = ensure_user("request.customer@example.test")
		self.team = make_team("Request Co", self.customer)
		frappe.set_user(self.customer)
		self.addCleanup(frappe.set_user, "Administrator")

	def test_confirming_asks_the_partner_with_a_requested_link(self):
		result = request_partner_link(team=self.team, p=self.p, paid_by_partner=1)
		link = frappe.get_doc("Partner Client Link", result["name"])
		self.assertEqual(
			(link.partner_team, link.client_team, link.status, link.paid_by_partner, link.source),
			(self.partner.team, self.team, "Requested", 1, "Partner Code"),
		)
		self.assertEqual(link.requested_by, self.customer)

	def test_an_account_asks_for_one_partner_at_a_time(self):
		request_partner_link(team=self.team, p=self.p)
		with self.assertRaises(frappe.ValidationError):
			request_partner_link(team=self.team, p=self.p)

	def test_only_someone_who_manages_the_accounts_billing_can_ask(self):
		frappe.set_user("Administrator")
		boss_team = make_team(
			"Boss Request Co", ensure_user("request.boss@example.test"), [(self.customer, "Developer")]
		)
		frappe.set_user(self.customer)
		with self.assertRaises(frappe.PermissionError):
			request_partner_link(team=boss_team, p=self.p)

	def test_a_bad_link_is_refused(self):
		with self.assertRaises(frappe.DoesNotExistError):
			request_partner_link(team=self.team, p="0" * 64)


class TestPartnerClientLinkPermissions(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.partner_owner = ensure_user("perm.partner@example.test")
		self.partner = make_partner("Perm Partner", self.partner_owner)
		self.customer = ensure_user("perm.customer@example.test")
		self.developer = ensure_user("perm.developer@example.test")
		self.outsider = ensure_user("perm.outsider@example.test")
		self.team = make_team("Perm Co", self.customer, [(self.developer, "Developer")])
		make_team("Outsider Co", self.outsider)

		frappe.set_user(self.customer)
		self.addCleanup(frappe.set_user, "Administrator")
		self.link = request_partner_link(team=self.team, p=self.partner.partner_code_hash)["name"]

	def visible_links(self, user: str) -> list[str]:
		frappe.set_user(user)
		return frappe.get_list("Partner Client Link", pluck="name")

	def test_the_client_and_the_partner_see_the_link(self):
		self.assertIn(self.link, self.visible_links(self.customer))
		self.assertIn(self.link, self.visible_links(self.partner_owner))

	def test_another_team_and_a_member_without_billing_see_nothing(self):
		self.assertEqual(self.visible_links(self.outsider), [])
		self.assertEqual(self.visible_links(self.developer), [])

	def test_another_team_cant_open_the_link_by_name(self):
		frappe.set_user(self.outsider)
		doc = frappe.get_doc("Partner Client Link", self.link)
		self.assertFalse(frappe.has_permission("Partner Client Link", "read", doc))

	def test_the_client_cant_approve_or_delete_its_own_link(self):
		doc = frappe.get_doc("Partner Client Link", self.link)
		doc.status = "Active"
		with self.assertRaises(frappe.PermissionError):
			doc.save()
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("Partner Client Link", self.link)

	def test_a_user_cant_create_an_approved_link_or_set_the_partners_spend_limit(self):
		frappe.set_user("Administrator")
		other_team = make_team("Perm Other Co", self.customer)
		frappe.set_user(self.customer)
		for values in ({"status": "Active"}, {"paid_by_partner": 1, "spend_limit": 500}):
			link = {
				"doctype": "Partner Client Link",
				"partner_team": self.partner.team,
				"client_team": other_team,
			}
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc({**link, **values}).insert()
