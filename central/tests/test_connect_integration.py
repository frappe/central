from urllib.parse import urlparse

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from central.api import connect, partners
from central.central.doctype.partner_client_link.partner_client_link import expire_requested_links
from central.central.doctype.partner_profile.partner_profile import hash_token
from central.identity.doctype.team_invitation.team_invitation import get_expiry_date
from central.tests.test_iam import ensure_user
from central.tests.test_partner_setup import make_partner, make_team
from central.users import CONNECT_INTEGRATION_USER, ensure_connect_integration_user

CONNECT = "https://connect.example.test"


def token_of(url: str) -> str:
	return urlparse(url).path.rsplit("/", 1)[-1]


class TestConnectIntegration(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.enterContext(self.change_settings("Central Settings", connect_url=CONNECT))
		ensure_connect_integration_user()
		# Records stay until the class ends, so each test gets its own partner and project.
		self.partner_id, self.project = (
			f"PTR-{frappe.generate_hash(length=8)}",
			f"CP-{frappe.generate_hash(length=8)}",
		)
		self.partner = make_partner("Connect Partner", ensure_user("connect.partner@example.test"))
		self.partner.db_set("connect_partner_id", self.partner_id)
		self.customer = ensure_user("connect.customer@example.test")
		frappe.set_user(CONNECT_INTEGRATION_USER)

	def create_link(self, **values):
		return connect.create_partner_link(
			**{
				"connect_partner_id": self.partner_id,
				"engagement_id": self.project,
				"customer_email": " Connect.Customer@example.test ",
				"project_title": "ERP rollout",
				"return_url": f"{CONNECT}/connect/projects/{self.project}",
				**values,
			}
		)

	def link(self):
		frappe.set_user("Administrator")
		name = frappe.db.get_value("Partner Client Link", {"source_reference": self.project})
		return frappe.get_doc("Partner Client Link", name)

	def test_a_hire_creates_a_requested_link_for_the_customers_email(self):
		result = self.create_link()
		link = self.link()

		self.assertEqual(result["status"], "Requested")
		self.assertIn("/dashboard/connect/customer/", result["url"])
		self.assertEqual(link.token_hash, hash_token(token_of(result["url"])))
		self.assertEqual(
			(link.source, link.partner_team, link.client_team, link.customer_email),
			("Connect", self.partner.team, None, self.customer),
		)
		self.assertEqual(str(link.expires_on), get_expiry_date())

	def test_asking_again_keeps_one_link_and_only_the_newest_url_works(self):
		first = self.create_link()
		frappe.set_user(CONNECT_INTEGRATION_USER)
		second = self.create_link()

		self.assertEqual(frappe.db.count("Partner Client Link", {"source_reference": self.project}), 1)
		self.assertNotEqual(token_of(first["url"]), token_of(second["url"]))
		self.assertEqual(self.link().token_hash, hash_token(token_of(second["url"])))

	def test_asking_again_after_the_link_stopped_returns_its_status_only(self):
		self.create_link()
		self.link().end("Project cancelled")
		frappe.set_user(CONNECT_INTEGRATION_USER)
		self.assertEqual(self.create_link(), {"status": "Ended"})

	def test_an_unregistered_partner_or_a_foreign_return_url_is_refused(self):
		for values in (
			{"connect_partner_id": "PTR-UNKNOWN"},
			{"return_url": "https://evil.example.test/connect"},
			{"return_url": f"http://connect.example.test/connect/projects/{self.project}"},
			{"customer_email": "not an email"},
		):
			with self.subTest(values=values), self.assertRaises(frappe.ValidationError):
				self.create_link(**values)

	def test_connect_reads_and_ends_the_link(self):
		self.create_link()
		self.assertEqual(connect.get_partner_link(self.project)["status"], "Requested")

		self.assertEqual(connect.end_partner_link(self.project, "Project cancelled"), {"status": "Ended"})
		link = self.link()
		self.assertEqual((link.ended_by, link.end_reason), (CONNECT_INTEGRATION_USER, "Project cancelled"))

		frappe.set_user(CONNECT_INTEGRATION_USER)
		self.assertEqual(connect.end_partner_link(self.project)["status"], "Ended")
		with self.assertRaises(frappe.DoesNotExistError):
			connect.get_partner_link("CP-UNKNOWN")

	def test_an_unanswered_link_expires(self):
		self.create_link()
		self.link().db_set("expires_on", add_days(today(), -1))

		frappe.set_user(CONNECT_INTEGRATION_USER)
		self.assertEqual(connect.get_partner_link(self.project)["status"], "Expired")
		frappe.set_user("Administrator")
		expire_requested_links()
		self.assertEqual(self.link().status, "Expired")

	def test_a_stopped_link_never_becomes_active_again(self):
		self.create_link()
		link = self.link()
		link.end()
		link.status = "Active"
		with self.assertRaises(frappe.ValidationError):
			link.save()

	def test_only_the_integration_user_can_call_connects_routes(self):
		frappe.set_user(self.customer)
		with self.assertRaises(frappe.PermissionError):
			self.create_link()
		with self.assertRaises(frappe.PermissionError):
			connect.register_partner("PTR-TEST-2", "Another Partner", self.customer)
		with self.assertRaises(frappe.PermissionError):
			connect.get_partner_registration("PTR-TEST-2")

	def test_the_integration_user_sees_only_connect_links(self):
		frappe.set_user("Administrator")
		team = make_team("Code Co", self.customer)
		code_link = frappe.get_doc(
			{"doctype": "Partner Client Link", "partner_team": self.partner.team, "client_team": team}
		).insert()

		frappe.set_user(CONNECT_INTEGRATION_USER)
		self.create_link()
		visible = frappe.get_list("Partner Client Link", pluck="name")
		self.assertIn(self.link().name, visible)
		self.assertNotIn(code_link.name, visible)


class TestConnectPartnerRegistration(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.enterContext(self.change_settings("Central Settings", connect_url=CONNECT))
		ensure_connect_integration_user()
		self.partner_id = f"PTR-{frappe.generate_hash(length=8)}"
		frappe.set_user(CONNECT_INTEGRATION_USER)

	def register(self):
		return connect.register_partner(self.partner_id, "Tridots", " Kiran@Tridots.example.test ")

	def profile(self):
		frappe.set_user("Administrator")
		return frappe.get_doc("Partner Profile", {"connect_partner_id": self.partner_id})

	def test_registering_asks_the_owner_to_pick_the_team(self):
		result = self.register()
		profile = self.profile()

		self.assertEqual(result["status"], "Pending")
		self.assertIn("/dashboard/connect/partner/", result["url"])
		self.assertEqual(profile.token_hash, hash_token(token_of(result["url"])))
		self.assertEqual(
			(profile.partner_name, profile.owner_email, profile.team),
			("Tridots", "kiran@tridots.example.test", None),
		)

	def test_the_owner_goes_back_to_the_connect_page_that_sent_them(self):
		back = f"{CONNECT}/connect/partner-onboarding"
		connect.register_partner(self.partner_id, "Tridots", "kiran@tridots.example.test", back)
		self.assertEqual(self.profile().get_summary()["connect_url"], back)

		frappe.set_user(CONNECT_INTEGRATION_USER)
		with self.assertRaises(frappe.ValidationError):
			connect.register_partner(
				f"{self.partner_id}-2", "Tridots", "kiran@tridots.example.test", "https://evil.example.test/"
			)

	def test_registering_again_keeps_one_profile_with_a_new_url(self):
		first = self.register()
		frappe.set_user(CONNECT_INTEGRATION_USER)
		second = self.register()

		self.assertEqual(frappe.db.count("Partner Profile", {"connect_partner_id": self.partner_id}), 1)
		self.assertEqual(self.profile().token_hash, hash_token(token_of(second["url"])))
		self.assertNotEqual(first["url"], second["url"])

	def test_connect_can_ask_how_the_registration_stands_without_a_new_url(self):
		self.assertEqual(connect.get_partner_registration(self.partner_id), {"status": None, "team": None})
		url = self.register()["url"]
		frappe.set_user(CONNECT_INTEGRATION_USER)
		self.assertEqual(
			connect.get_partner_registration(self.partner_id), {"status": "Pending", "team": None}
		)
		self.assertEqual(self.profile().token_hash, hash_token(token_of(url)))

	def test_a_completed_registration_returns_its_team(self):
		self.register()
		profile = self.profile()
		profile.update(
			{
				"team": make_team("Tridots Co", ensure_user("kiran@tridots.example.test")),
				"status": "Completed",
			}
		)
		profile.save()

		frappe.set_user(CONNECT_INTEGRATION_USER)
		self.assertEqual(self.register(), {"status": "Completed", "team": profile.team})

	def test_a_pending_partner_cant_be_linked_to_customers(self):
		self.register()
		frappe.set_user(CONNECT_INTEGRATION_USER)
		with self.assertRaises(frappe.ValidationError):
			connect.create_partner_link(
				self.partner_id,
				"CP-REG-1",
				"asha@example.test",
				"ERP",
				f"{CONNECT}/connect/projects/CP-REG-1",
			)


class TestPartnerRegistrationPage(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.enterContext(self.change_settings("Central Settings", connect_url=CONNECT))
		ensure_connect_integration_user()
		self.owner = ensure_user("reg.owner@example.test")
		self.team = make_team("Reg Partner Co", self.owner)
		frappe.set_user(CONNECT_INTEGRATION_USER)
		self.token = token_of(
			connect.register_partner(f"PTR-{frappe.generate_hash(length=8)}", "Tridots", self.owner)["url"]
		)
		frappe.set_user(self.owner)

	def test_the_link_shows_who_it_is_for(self):
		frappe.set_user("Guest")
		summary = partners.get_partner_registration(self.token)
		self.assertEqual(
			(summary["partner_name"], summary["email"], summary["status"]), ("Tridots", self.owner, "Pending")
		)
		with self.assertRaises(frappe.DoesNotExistError):
			partners.get_partner_registration("not-a-token")

	def test_the_owner_picks_the_team_once(self):
		self.assertEqual(partners.complete_partner_registration(self.token, self.team)["team"], self.team)
		self.assertTrue(frappe.db.exists("Partner Profile", {"team": self.team, "status": "Completed"}))
		with self.assertRaises(frappe.DoesNotExistError):
			partners.complete_partner_registration(self.token, self.team)

	def test_someone_else_cant_complete_it(self):
		frappe.set_user("Administrator")
		other = ensure_user("reg.other@example.test")
		other_team = make_team("Reg Other Co", other)
		frappe.set_user(other)
		with self.assertRaises(frappe.PermissionError):
			partners.complete_partner_registration(self.token, other_team)

	def test_a_team_the_owner_cant_manage_or_that_has_a_partner_is_refused(self):
		frappe.set_user("Administrator")
		boss_team = make_team(
			"Reg Boss Co", ensure_user("reg.boss@example.test"), [(self.owner, "Developer")]
		)
		client_team = make_team("Reg Client Co", self.owner)
		other_partner = make_partner("Reg Other Partner", ensure_user("reg.otherpartner@example.test"))
		frappe.get_doc(
			{
				"doctype": "Partner Client Link",
				"partner_team": other_partner.team,
				"client_team": client_team,
				"status": "Active",
			}
		).insert()

		frappe.set_user(self.owner)
		with self.assertRaises(frappe.PermissionError):
			partners.complete_partner_registration(self.token, boss_team)
		with self.assertRaises(frappe.ValidationError):
			partners.complete_partner_registration(self.token, client_team)


class TestCustomerAnswer(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.enterContext(self.change_settings("Central Settings", connect_url=CONNECT))
		ensure_connect_integration_user()
		self.partner_id, self.project = (
			f"PTR-{frappe.generate_hash(length=8)}",
			f"CP-{frappe.generate_hash(length=8)}",
		)
		self.partner = make_partner("Answer Partner", ensure_user("answer.partner@example.test"))
		self.partner.db_set("connect_partner_id", self.partner_id)
		self.customer = ensure_user(f"asha.{frappe.generate_hash(length=6)}@example.test")
		self.team = make_team("Northwind", self.customer)

		frappe.set_user(CONNECT_INTEGRATION_USER)
		self.token = token_of(
			connect.create_partner_link(
				self.partner_id,
				self.project,
				self.customer,
				"ERP rollout",
				f"{CONNECT}/connect/projects/{self.project}",
			)["url"]
		)
		frappe.set_user(self.customer)
		self.request = partners.get_partner_request(self.token)["name"]

	def status(self):
		frappe.set_user(CONNECT_INTEGRATION_USER)
		return connect.get_partner_link(self.project)

	def test_the_customer_sees_the_request_with_teams_that_can_accept(self):
		(request,) = partners.my_partner_requests()
		self.assertEqual((request["name"], request["project_title"]), (self.request, "ERP rollout"))
		self.assertEqual([team["name"] for team in request["teams"] if team["available"]], [self.team])

		frappe.set_user("Administrator")
		frappe.set_user(ensure_user("answer.outsider@example.test"))
		self.assertEqual(partners.my_partner_requests(), [])

	def test_a_partner_who_pays_gets_access(self):
		result = partners.accept_partner_request(self.request, team=self.team, paid_by_partner=1)
		self.assertEqual(
			(result["status"], result["team"], result["partner_access"]), ("Active", self.team, 1)
		)
		self.assertEqual((self.status()["status"], self.status()["customer_team"]), ("Active", self.team))

		frappe.set_user(self.customer)
		with self.assertRaises(frappe.DoesNotExistError):
			partners.get_partner_request(self.token)

	def test_a_customer_who_pays_decides_on_access_now_or_later(self):
		self.assertEqual(partners.accept_partner_request(self.request, team=self.team)["partner_access"], 0)
		partners.set_team_partner_access(self.team, self.request, 1)
		self.assertEqual(frappe.db.get_value("Partner Client Link", self.request, "partner_access"), 1)

	def test_a_partner_who_pays_keeps_access(self):
		partners.accept_partner_request(self.request, team=self.team, paid_by_partner=1)
		with self.assertRaises(frappe.ValidationError):
			partners.set_team_partner_access(self.team, self.request, 0)

	def test_the_hire_takes_over_an_earlier_link_with_the_same_partner(self):
		frappe.set_user("Administrator")
		earlier = frappe.get_doc(
			{"doctype": "Partner Client Link", "partner_team": self.partner.team, "client_team": self.team}
		).insert()
		frappe.set_user(self.customer)
		(request,) = partners.my_partner_requests()
		self.assertTrue(next(team for team in request["teams"] if team["name"] == self.team)["available"])

		partners.accept_partner_request(self.request, team=self.team)
		self.assertEqual(frappe.db.get_value("Partner Client Link", earlier.name, "status"), "Ended")
		self.assertEqual(frappe.db.get_value("Partner Client Link", self.request, "status"), "Active")

	def test_only_the_customer_can_answer(self):
		frappe.set_user("Administrator")
		outsider = ensure_user("answer.intruder@example.test")
		outsider_team = make_team("Intruder Co", outsider)
		frappe.set_user(outsider)
		with self.assertRaises(frappe.PermissionError):
			partners.accept_partner_request(self.request, team=outsider_team)

	def test_a_team_with_another_partner_cant_accept(self):
		frappe.set_user("Administrator")
		other_partner = make_partner("Answer Other Partner", ensure_user("answer.other@example.test"))
		frappe.get_doc(
			{
				"doctype": "Partner Client Link",
				"partner_team": other_partner.team,
				"client_team": self.team,
				"status": "Active",
			}
		).insert()
		frappe.set_user(self.customer)
		with self.assertRaises(frappe.ValidationError):
			partners.accept_partner_request(self.request, team=self.team)


class TestTeamPartners(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.partner_owner = ensure_user("teampartners.partner@example.test")
		self.partner = make_partner("Team Partners Partner", self.partner_owner)
		self.customer = ensure_user("teampartners.customer@example.test")
		self.developer = ensure_user("teampartners.dev@example.test")
		self.team = make_team("Team Partners Co", self.customer, [(self.developer, "Developer")])
		self.link = frappe.get_doc(
			{
				"doctype": "Partner Client Link",
				"partner_team": self.partner.team,
				"client_team": self.team,
				"status": "Active",
				"paid_by_partner": 1,
			}
		).insert()

	def test_the_customer_sees_its_partner_and_the_partner_its_client(self):
		frappe.set_user(self.customer)
		partner = partners.get_team_partners(self.team)["partner"]
		self.assertEqual(
			(partner["name"], partner["partner_name"], partner["paid_by_partner"]),
			(self.link.name, "Team Partners Partner", True),
		)

		frappe.set_user(self.partner_owner)
		result = partners.get_team_partners(self.partner.team)
		self.assertTrue(result["is_partner"])
		self.assertEqual([client["client_name"] for client in result["clients"]], ["Team Partners Co"])

	def test_either_side_can_end_it_and_others_cant(self):
		frappe.set_user(self.developer)
		with self.assertRaises(frappe.PermissionError):
			partners.end_team_partner_link(self.team, self.link.name)

		frappe.set_user("Administrator")
		unrelated_team = make_team("Unrelated Co", self.partner_owner)
		frappe.set_user(self.partner_owner)
		with self.assertRaises(frappe.PermissionError):
			partners.end_team_partner_link(unrelated_team, self.link.name)

		self.assertEqual(
			partners.end_team_partner_link(self.partner.team, self.link.name, "Contract over")["status"],
			"Ended",
		)
		link = frappe.get_doc("Partner Client Link", self.link.name)
		self.assertEqual((link.ended_by, link.end_reason), (self.partner_owner, "Contract over"))
