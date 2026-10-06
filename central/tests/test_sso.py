import frappe
from frappe.tests import IntegrationTestCase

from central.central.doctype.central_sso_settings.central_sso_settings import CentralSSOSettings
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
