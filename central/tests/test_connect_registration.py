import frappe
from frappe.tests import IntegrationTestCase

from central.api.connect import get_partner_registration, register_partner
from central.api.partners import complete_partner_registration
from central.api.partners import get_partner_registration as get_registration_summary
from central.tests.test_team_management import create_user
from central.tests.utils import central_limit

CONNECT_URL = "https://connect.example.test"
RETURN_URL = f"{CONNECT_URL}/connect/partner-onboarding"


class TestConnectRegistration(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("Central Settings", "connect_url", CONNECT_URL)
		self.integration = self._create_integration_user()
		self.partner_id = f"PARTNER-{frappe.generate_hash(length=8)}"
		self.owner = create_user(f"partner.owner.{frappe.generate_hash(length=6)}@example.test")
		self.team = self._create_team("Tridots Tech", self.owner)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_only_the_integration_role_can_register(self):
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.PermissionError):
			register_partner(self.partner_id, "Tridots", self.owner)

	def test_return_url_must_be_on_the_connect_host(self):
		frappe.set_user(self.integration)
		with self.assertRaises(frappe.ValidationError):
			register_partner(self.partner_id, "Tridots", self.owner, "https://evil.example.test/back")

	def test_a_partner_is_pending_until_a_team_represents_it(self):
		frappe.set_user(self.integration)
		self.assertEqual(get_partner_registration(self.partner_id), {"status": "Pending"})

	def test_owner_completes_and_connect_reads_the_code(self):
		token = self._token(self._register())

		frappe.set_user(self.owner)
		summary = get_registration_summary(token)
		self.assertEqual(
			(summary["status"], [team.name for team in summary["teams"]]), ("Pending", [self.team])
		)

		result = complete_partner_registration(token, self.team)
		self.assertEqual(result, {"team": self.team, "return_url": RETURN_URL})
		self.assertEqual(complete_partner_registration(token, self.team), result)

		frappe.set_user(self.integration)
		status = get_partner_registration(self.partner_id)
		self.assertEqual((status["status"], status["team"]), ("Completed", self.team))
		self.assertRegex(status["partner_code"], r"^TRI-\d{5}$")
		self.assertEqual(self._register()["partner_code"], status["partner_code"])

	def test_wrong_email_cannot_complete(self):
		token = self._token(self._register())
		stranger = create_user(f"stranger.{frappe.generate_hash(length=6)}@example.test")
		stranger_team = self._create_team("Stranger Team", stranger)

		frappe.set_user(stranger)
		self.assertEqual(get_registration_summary(token)["teams"], [])
		with self.assertRaises(frappe.PermissionError):
			complete_partner_registration(token, stranger_team)

	def test_owner_cannot_choose_a_team_they_do_not_own(self):
		token = self._token(self._register())
		admin_team = self._create_team("Shared Team", create_user("shared.owner@example.test"))
		shared = frappe.get_doc("Team", admin_team)
		shared.append("members", {"user": self.owner, "role": "Admin", "status": "Active"})
		shared.save()
		foreign_team = self._create_team("Foreign Team", create_user("foreign.owner@example.test"))

		frappe.set_user(self.owner)
		for team in (admin_team, foreign_team):
			with self.assertRaises(frappe.PermissionError):
				complete_partner_registration(token, team)

	def test_a_tampered_or_expired_link_is_refused(self):
		token = self._token(self._register())
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.DoesNotExistError):
			complete_partner_registration(
				token[:-2] + ("AA" if not token.endswith("AA") else "BB"), self.team
			)

		with central_limit("invitation_expiry_days", -1):
			expired = self._token(self._register())
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.DoesNotExistError):
			complete_partner_registration(expired, self.team)

	def test_a_partner_team_cannot_represent_a_second_partner(self):
		token = self._token(self._register())
		frappe.set_user(self.owner)
		complete_partner_registration(token, self.team)

		self.partner_id = f"PARTNER-{frappe.generate_hash(length=8)}"
		second = self._token(self._register())
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.ValidationError):
			complete_partner_registration(second, self.team)

	def test_team_admin_cannot_set_the_partner_fields(self):
		frappe.set_user(self.owner)
		team = frappe.get_doc("Team", self.team)
		team.connect_partner_id = "PARTNER-forged"
		team.partner_code = "FOR-00000"
		team.save()

		self.assertEqual(
			frappe.db.get_value("Team", self.team, ["connect_partner_id", "partner_code"]), (None, None)
		)

	def _register(self) -> dict:
		frappe.set_user(self.integration)
		result = register_partner(self.partner_id, "Tridots", self.owner, RETURN_URL)
		frappe.set_user("Administrator")
		return result

	def _token(self, result: dict) -> str:
		return result["url"].rsplit("/partner-registration/", 1)[1]

	def _create_team(self, team_name: str, owner: str) -> str:
		frappe.set_user("Administrator")
		return (
			frappe.get_doc(
				{
					"doctype": "Team",
					"team_name": team_name,
					"owner_user": owner,
					"members": [{"user": owner, "role": "Owner", "status": "Active"}],
				}
			)
			.insert()
			.name
		)

	def _create_integration_user(self) -> str:
		user = create_user("connect.integration@example.test")
		doc = frappe.get_doc("User", user)
		if "Connect Integration" not in frappe.get_roles(user):
			doc.add_roles("Connect Integration")
		return user
