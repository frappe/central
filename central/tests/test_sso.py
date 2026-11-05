import frappe
import jwt
from frappe.tests import IntegrationTestCase

from central.central.doctype.central_sso_settings.central_sso_settings import (
	MAXIMUM_BENCH_SESSION_MINUTES,
	CentralSSOSettings,
)
from central.sso import central_url


class TestCentralSSO(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		CentralSSOSettings.instance().initialize_signing_key("pilot")

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_bootstrap_verifier_rejects_other_scopes(self):
		# scope is an asserted claim, not a convention: bench-login is signed with this
		# same key, so only the scope check stops it being accepted as an enrollment
		# token. A datum token is refused on its signature, because the Atlas key signs it.
		from central.sso import (
			mint_bench_login,
			mint_bootstrap_token,
			mint_datum_token,
			verify_bootstrap_token,
		)

		CentralSSOSettings.instance().initialize_signing_key("atlas")
		enroll = mint_bootstrap_token("team-x", "pcred-x")
		self.assertEqual(verify_bootstrap_token(enroll)["team"], "team-x")

		for other in (mint_bench_login("pcred-x"), mint_datum_token(42, "vm-1")):
			with self.assertRaises(frappe.AuthenticationError):
				verify_bootstrap_token(other)


class TestCentralUrl(IntegrationTestCase):
	def tearDown(self):
		frappe.db.set_single_value("Central SSO Settings", "issuer_url", "")

	def test_prefers_the_configured_issuer_url(self):
		frappe.db.set_single_value("Central SSO Settings", "issuer_url", "https://central.example.test")
		self.assertEqual(central_url(), "https://central.example.test")

	def test_falls_back_to_the_site_url_when_unset(self):
		frappe.db.set_single_value("Central SSO Settings", "issuer_url", "")
		self.assertEqual(central_url(), frappe.utils.get_url())


class TestBenchSessionLength(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		CentralSSOSettings.instance().initialize_signing_key("pilot")

	def tearDown(self):
		frappe.db.set_single_value("Central SSO Settings", "bench_session_minutes", 60)

	def get_lifetime(self, token: str) -> int:
		claims = jwt.decode(token, options={"verify_signature": False})
		return claims["exp"] - claims["iat"]

	def save_minutes(self, minutes: int) -> None:
		settings = CentralSSOSettings.instance()
		settings.bench_session_minutes = minutes
		settings.save()

	def test_sign_in_link_lasts_the_configured_session_length(self):
		from central.sso import mint_bench_login

		self.save_minutes(480)
		self.assertEqual(self.get_lifetime(mint_bench_login("pilot-audience")), 480 * 60)

	def test_api_bearer_keeps_its_short_lifetime(self):
		from central.sso import BENCH_API_TTL, mint_bench_api_token

		self.save_minutes(480)
		token = mint_bench_api_token("pilot-audience")
		self.assertEqual(self.get_lifetime(token), BENCH_API_TTL)
		self.assertEqual(jwt.decode(token, options={"verify_signature": False})["scope"], "bench")

	def test_session_length_outside_the_allowed_range_is_rejected(self):
		for minutes in (0, -5, MAXIMUM_BENCH_SESSION_MINUTES + 1):
			with self.subTest(minutes=minutes), self.assertRaises(frappe.ValidationError):
				self.save_minutes(minutes)

		self.save_minutes(MAXIMUM_BENCH_SESSION_MINUTES)

	def test_unset_session_length_uses_the_default(self):
		from central.sso import mint_bench_login

		frappe.db.delete("Singles", {"doctype": "Central SSO Settings", "field": "bench_session_minutes"})
		frappe.clear_document_cache("Central SSO Settings", "Central SSO Settings")
		self.assertEqual(self.get_lifetime(mint_bench_login("pilot-audience")), 60 * 60)

		CentralSSOSettings.instance().save()
		self.assertEqual(frappe.db.get_single_value("Central SSO Settings", "bench_session_minutes"), 60)
