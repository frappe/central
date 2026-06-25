from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.auth import build_auth_context, sign_up


class TestAuth(IntegrationTestCase):
	def test_guest_context(self):
		frappe.set_user("Guest")

		context = build_auth_context()

		self.assertEqual(context["user"], "Guest")
		self.assertIsInstance(context["provider_logins"], list)

	@IntegrationTestCase.change_settings("Website Settings", disable_signup=1)
	def test_central_signup_works_when_website_signup_is_disabled(self):
		frappe.set_user("Guest")
		email = "central-signup-test@example.test"

		with patch("frappe.core.doctype.user.user.User.send_welcome_mail_to_user"):
			status, _message = sign_up(email, "Central Signup Test")

		self.assertEqual(status, 1)
		self.assertEqual(frappe.db.get_value("User", email, "user_type"), "Website User")
		self.assertEqual(frappe.cache.hget("redirect_after_login", email), "/dashboard/servers")
		frappe.cache.hdel("redirect_after_login", email)

	def test_signup_rejects_existing_user(self):
		status, message = sign_up("Administrator", "Administrator")

		self.assertEqual(status, 0)
		self.assertEqual(message, "Already Registered")
