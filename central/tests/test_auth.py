from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.auth import (
	OTP_TTL_SECONDS,
	_login_otp_key,
	_otp_key,
	_send_signup_code,
	request_login_code,
	resend_signup_code,
	sign_up,
	verify_login_code,
	verify_signup,
)
from central.www.dashboard import build_auth_context


class TestAuth(IntegrationTestCase):
	def test_email_code_signs_in_once_without_a_password(self):
		email = frappe.db.get_value("User", "Administrator", "email").lower()
		self.addCleanup(frappe.cache.delete_value, _login_otp_key(email))
		frappe.set_user("Guest")

		with patch("central.api.auth.frappe.sendmail") as sendmail:
			response = request_login_code(email)
		self.assertIn("If this email", response["message"])
		self.assertEqual(sendmail.call_args.kwargs["recipients"], [email])
		code = frappe.cache.get_value(_login_otp_key(email))["code"]

		with patch("frappe.local.login_manager", create=True) as login_manager:
			login_manager.login_as.side_effect = frappe.set_user
			self.assertEqual(verify_login_code(email, code)["user"], "Administrator")
			login_manager.login_as.assert_called_once_with("Administrator")
			with self.assertRaises(frappe.ValidationError):
				verify_login_code(email, code)

	def test_login_does_not_disclose_an_unknown_or_disabled_account(self):
		frappe.set_user("Guest")
		with patch("central.api.auth.frappe.sendmail") as sendmail:
			unknown = request_login_code("missing-login@example.test")
			with patch("central.api.auth.frappe.db.get_value", return_value=0):
				disabled = request_login_code("disabled@example.test")
		self.assertEqual(unknown, disabled)
		sendmail.assert_not_called()

	def test_login_code_keeps_failed_attempts_across_resends(self):
		email = frappe.db.get_value("User", "Administrator", "email").lower()
		self.addCleanup(frappe.cache.delete_value, _login_otp_key(email))
		frappe.set_user("Guest")
		with patch("central.api.auth.frappe.sendmail"):
			request_login_code(email)
			for _ in range(4):
				with self.assertRaises(frappe.ValidationError):
					verify_login_code(email, "000000")
			request_login_code(email)
		self.assertEqual(frappe.cache.get_value(_login_otp_key(email))["attempts"], 4)
		with self.assertRaises(frappe.ValidationError):
			verify_login_code(email, "000000")
		with self.assertRaises(frappe.ValidationError):
			verify_login_code(email, frappe.cache.get_value(_login_otp_key(email))["code"])

	def test_disabling_account_after_code_send_blocks_login(self):
		email = frappe.db.get_value("User", "Administrator", "email").lower()
		self.addCleanup(frappe.cache.delete_value, _login_otp_key(email))
		frappe.set_user("Guest")
		with patch("central.api.auth.frappe.sendmail"):
			request_login_code(email)
		code = frappe.cache.get_value(_login_otp_key(email))["code"]
		with (
			patch(
				"central.api.auth.frappe.db.get_value",
				return_value=frappe._dict(name="Administrator", enabled=0),
			),
			patch("frappe.local.login_manager", create=True) as login_manager,
		):
			with self.assertRaises(frappe.ValidationError):
				verify_login_code(email, code)
			login_manager.login_as.assert_not_called()

	def test_login_rejects_malformed_email_and_code(self):
		with self.assertRaises(frappe.ValidationError):
			request_login_code("not-an-email")
		with self.assertRaises(frappe.ValidationError):
			request_login_code("one@example.test,two@example.test")
		with self.assertRaises(frappe.ValidationError):
			verify_login_code("valid@example.test", "12345x")

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

	def test_verify_without_a_pending_signup_is_refused(self):
		frappe.set_user("Guest")
		email = "central-missing-signup-test@example.test"
		self.addCleanup(frappe.cache.delete_value, _otp_key(email))

		with self.assertRaises(frappe.ValidationError):
			with patch("frappe.local.login_manager", create=True):
				verify_signup(email, "123456")

		self.assertFalse(frappe.db.exists("User", email))

	@IntegrationTestCase.change_settings("Website Settings", disable_signup=1)
	def test_a_wrong_code_is_refused_in_developer_mode(self):
		frappe.set_user("Guest")
		email = "central-wrong-code-test@example.test"
		self.addCleanup(frappe.cache.delete_value, _otp_key(email))
		sign_up(email, "Wrong Code Test")
		code = frappe.cache.get_value(_otp_key(email))["code"]
		wrong = "000000" if code != "000000" else "111111"

		with patch.dict(frappe.conf, {"developer_mode": 1}):
			with self.assertRaises(frappe.ValidationError):
				with patch("frappe.local.login_manager", create=True):
					verify_signup(email, wrong)

		self.assertFalse(frappe.db.exists("User", email))

	def test_signup_rejects_existing_user(self):
		status, message = sign_up("Administrator", "Administrator")

		self.assertEqual(status, 0)
		self.assertEqual(message, "Already Registered")

	def test_signup_code_uses_the_documented_ten_minute_expiry(self):
		with (
			patch("central.api.auth.frappe.cache.set_value") as set_value,
			patch("central.api.auth.frappe.sendmail"),
		):
			_send_signup_code("expiry@example.test", "Expiry Test")

		self.assertEqual(OTP_TTL_SECONDS, 10 * 60)
		self.assertEqual(set_value.call_args.kwargs["expires_in_sec"], 10 * 60)

	def test_signup_email_states_the_code_and_its_expiry(self):
		with patch("central.api.auth.frappe.sendmail") as sendmail:
			_send_signup_code("template@example.test", "Template Test")

		code = frappe.cache.get_value(_otp_key("template@example.test"))["code"]
		html = frappe.render_template(
			"templates/emails/verification_code.html", sendmail.call_args.kwargs["args"]
		)
		self.assertEqual(sendmail.call_args.kwargs["template"], "verification_code")
		self.assertIn(code, html)
		self.assertIn("It expires in 10 minutes.", html)

	def test_resending_a_code_preserves_failed_attempts(self):
		with (
			patch("central.api.auth.frappe.cache.set_value") as set_value,
			patch("central.api.auth.frappe.sendmail"),
		):
			_send_signup_code("attempts@example.test", "Attempts Test", attempts=3)

		self.assertEqual(set_value.call_args.args[1]["attempts"], 3)

	def test_signup_and_resend_share_a_send_limit_for_email(self):
		email = f"limit.{frappe.generate_hash(length=8)}@example.test"
		self.addCleanup(frappe.cache.delete_value, _otp_key(email))

		with (
			patch.object(frappe.local, "request", SimpleNamespace(method="POST"), create=True),
			patch.object(frappe.local, "form_dict", {"email": email}, create=True),
			patch.object(frappe.local, "request_ip", f"test-{frappe.generate_hash(length=8)}", create=True),
			patch("central.api.auth.frappe.sendmail") as sendmail,
		):
			for _ in range(4):
				sign_up(email, "Limit Test")
			resend_signup_code(email)
			with self.assertRaises(frappe.RateLimitExceededError):
				sign_up(email, "Limit Test")

		self.assertEqual(sendmail.call_count, 5)

	def test_new_signup_code_does_not_reset_failed_attempts(self):
		email = f"attempts.{frappe.generate_hash(length=8)}@example.test"
		self.addCleanup(frappe.cache.delete_value, _otp_key(email))

		with patch("central.api.auth.frappe.sendmail"):
			sign_up(email, "Attempt Test")
			for _ in range(4):
				with self.assertRaises(frappe.ValidationError):
					verify_signup(email, "000000")

			sign_up(email, "Attempt Test")
			self.assertEqual(frappe.cache.get_value(_otp_key(email))["attempts"], 4)
			with self.assertRaises(frappe.ValidationError):
				verify_signup(email, "000000")
			with self.assertRaises(frappe.ValidationError):
				sign_up(email, "Attempt Test")
			with self.assertRaises(frappe.ValidationError):
				resend_signup_code(email)
			code = frappe.cache.get_value(_otp_key(email))["code"]
			with self.assertRaises(frappe.ValidationError):
				verify_signup(email, code)
