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

		# Step 2: the cached code creates the Website User and (via bootstrap_user_team)
		# its personal team, then logs the user in. login_manager only exists on a real
		# request, so stub it here.
		code = frappe.cache.get_value(_otp_key(email))["code"]
		with patch("frappe.local.login_manager", create=True):
			result = verify_signup(email, code)

		self.assertEqual(frappe.db.get_value("User", email, "user_type"), "Website User")
		self.assertTrue(result["team"])
		self.assertIsNone(frappe.cache.get_value(_otp_key(email)))

	def test_signup_rejects_existing_user(self):
		status, message = sign_up("Administrator", "Administrator")

		self.assertEqual(status, 0)
		self.assertEqual(message, "Already Registered")
