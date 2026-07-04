from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.auth import _otp_key, build_auth_context, sign_up, verify_signup


class TestAuth(IntegrationTestCase):
	def test_guest_context(self):
		frappe.set_user("Guest")

		context = build_auth_context()

		self.assertEqual(context["user"], "Guest")
		self.assertIsInstance(context["provider_logins"], list)
		self.assertFalse(context["onboarding_complete"])

	@IntegrationTestCase.change_settings("Website Settings", disable_signup=1)
	def test_signup_is_otp_verified_then_creates_a_website_user(self):
		frappe.set_user("Guest")
		email = "central-signup-test@example.test"
		self.addCleanup(frappe.cache.delete_value, _otp_key(email))

		# Step 1: sign_up emails a code and holds the pending signup in cache —
		# no User exists until the code is verified.
		status, _message = sign_up(email, "Central Signup Test")
		self.assertEqual(status, 1)
		self.assertFalse(frappe.db.exists("User", email))

		# Step 2: the cached code creates the Website User, logs it in, then provisions
		# its Central role and personal team as the authenticated user. login_manager
		# only exists on a real request, so stub the session transition here.
		code = frappe.cache.get_value(_otp_key(email))["code"]
		with patch("frappe.local.login_manager", create=True) as login_manager:
			login_manager.login_as.side_effect = frappe.set_user
			result = verify_signup(email, code)

		self.assertEqual(frappe.session.user, email)
		self.assertEqual(frappe.db.get_value("User", email, "user_type"), "Website User")
		self.assertIn("Central User", frappe.get_roles(email))
		self.assertTrue(result["team"])
		self.assertIsNone(frappe.cache.get_value(_otp_key(email)))

	@IntegrationTestCase.change_settings("Website Settings", disable_signup=1)
	def test_signup_seeds_billing_profile_currency_from_ip_country(self):
		frappe.set_user("Guest")
		email = "central-signup-geo-test@example.test"
		self.addCleanup(frappe.cache.delete_value, _otp_key(email))

		sign_up(email, "Geo Signup Test")
		code = frappe.cache.get_value(_otp_key(email))["code"]

		with (
			patch("frappe.local.login_manager", create=True) as login_manager,
			patch("central.geo.get_country_from_ip", return_value="India"),
		):
			login_manager.login_as.side_effect = frappe.set_user
			result = verify_signup(email, code)

		team = result["team"]
		# India → INR profile, stamped despite no legal name / address (ignore_mandatory).
		self.assertEqual(frappe.db.get_value("Billing Profile", team, "country"), "India")
		self.assertEqual(frappe.db.get_value("Billing Profile", team, "currency"), "INR")
		# Welcome credits are granted in that currency.
		self.assertTrue(
			frappe.db.exists(
				"Credit Ledger Entry", {"team": team, "reference_type": "Promotion", "currency": "INR"}
			)
		)

	@IntegrationTestCase.change_settings("Website Settings", disable_signup=1)
	def test_signup_falls_back_to_india_inr_when_ip_country_is_unknown(self):
		frappe.set_user("Guest")
		email = "central-signup-nogeo-test@example.test"
		self.addCleanup(frappe.cache.delete_value, _otp_key(email))

		sign_up(email, "No Geo Signup Test")
		code = frappe.cache.get_value(_otp_key(email))["code"]

		# get_country_from_ip returns None for localhost/private IPs (and in tests).
		with (
			patch("frappe.local.login_manager", create=True) as login_manager,
			patch("central.geo.get_country_from_ip", return_value=None),
		):
			login_manager.login_as.side_effect = frappe.set_user
			result = verify_signup(email, code)

		team = result["team"]
		# Unknown country → default to India / INR, and the two must agree.
		self.assertEqual(frappe.db.get_value("Billing Profile", team, "country"), "India")
		self.assertEqual(frappe.db.get_value("Billing Profile", team, "currency"), "INR")
		self.assertTrue(
			frappe.db.exists(
				"Credit Ledger Entry", {"team": team, "reference_type": "Promotion", "currency": "INR"}
			)
		)

	def test_developer_otp_bypass_still_requires_a_pending_signup(self):
		frappe.set_user("Guest")
		email = "central-missing-signup-test@example.test"
		self.addCleanup(frappe.cache.delete_value, _otp_key(email))
		original_developer_mode = frappe.conf.developer_mode
		frappe.conf.developer_mode = 1
		self.addCleanup(setattr, frappe.conf, "developer_mode", original_developer_mode)

		with self.assertRaises(frappe.ValidationError):
			with patch("frappe.local.login_manager", create=True):
				verify_signup(email, "123456")

		self.assertFalse(frappe.db.exists("User", email))

	def test_signup_rejects_existing_user(self):
		status, message = sign_up("Administrator", "Administrator")

		self.assertEqual(status, 0)
		self.assertEqual(message, "Already Registered")
