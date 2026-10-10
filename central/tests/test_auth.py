from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.auth import send_code, verify_code
from central.identity.email_code import EmailCode, EmailCodeError
from central.tests.test_team_management import create_user
from central.www.dashboard import build_auth_context

SENDMAIL = "central.identity.email_code.frappe.sendmail"


class TestAuth(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Guest")
		self.email = f"auth.{frappe.generate_hash(length=8)}@example.test"
		self.addCleanup(EmailCode(self.email).discard)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_new_email_gets_an_account_when_its_code_is_verified(self):
		with patch(SENDMAIL) as sendmail:
			send_code(self.email, "New Person")
		self.assertIn("signup code", sendmail.call_args.kwargs["subject"])
		self.assertEqual(sendmail.call_args.kwargs["args"]["heading"], "Create your Frappe Cloud account")
		self.assertFalse(frappe.db.exists("User", self.email))

		result = self._verify(self._code())

		self.assertEqual(result, {"user": self.email})
		self.assertEqual(frappe.session.user, self.email)
		self.assertEqual(frappe.db.get_value("User", self.email, "user_type"), "Website User")
		self.assertEqual(frappe.db.get_value("User", self.email, "full_name"), "New Person")
		self.assertIn("Central User", frappe.get_roles(self.email))
		self.assertIsNone(EmailCode(self.email).pending)

	def test_a_new_email_without_a_name_keeps_its_code_until_the_name_arrives(self):
		with patch(SENDMAIL):
			send_code(self.email)
		code = self._code()

		self.assertEqual(self._verify(code), {"needs_name": True})
		self.assertFalse(frappe.db.exists("User", self.email))

		self.assertEqual(self._verify(code, full_name="Late Name"), {"user": self.email})
		self.assertEqual(frappe.db.get_value("User", self.email, "full_name"), "Late Name")

	def test_an_existing_email_signs_in_and_keeps_its_name(self):
		frappe.set_user("Administrator")
		create_user(self.email)
		frappe.set_user("Guest")

		with patch(SENDMAIL) as sendmail:
			response = send_code(self.email, "Another Name")
		self.assertIn("sign-in code", sendmail.call_args.kwargs["subject"])
		self.assertEqual(sendmail.call_args.kwargs["args"]["heading"], "Sign in to Frappe Cloud")

		self.assertEqual(self._verify(self._code()), {"user": self.email})
		self.assertEqual(frappe.db.get_value("User", self.email, "first_name"), self.email.split("@")[0])
		self.assertEqual(response, {"message": f"We sent a code to {self.email}."})

	def test_a_code_signs_in_once(self):
		with patch(SENDMAIL):
			send_code(self.email, "Once Only")
		code = self._code()
		self._verify(code)

		with self.assertRaises(EmailCodeError):
			self._verify(code)

	def test_wrong_codes_lock_the_email_and_a_resend_does_not_unlock_it(self):
		with patch(SENDMAIL):
			send_code(self.email, "Locked Out")
			code = self._code()
			wrong = "000000" if code != "000000" else "111111"
			for _ in range(EmailCode.MAX_ATTEMPTS):
				with self.assertRaises(EmailCodeError):
					self._verify(wrong)

			with self.assertRaises(EmailCodeError) as resend:
				send_code(self.email)
			with self.assertRaises(EmailCodeError):
				self._verify(code)

		self.assertIn("Too many incorrect codes", str(resend.exception))
		self.assertFalse(frappe.db.exists("User", self.email))

	def test_a_code_that_was_never_sent_is_refused(self):
		with self.assertRaises(EmailCodeError) as refused:
			self._verify("123456")

		self.assertIn("expired", str(refused.exception))

	def test_a_disabled_account_looks_like_any_other_email_and_gets_no_code(self):
		frappe.set_user("Administrator")
		create_user(self.email)
		frappe.db.set_value("User", self.email, "enabled", 0)
		frappe.set_user("Guest")

		with patch(SENDMAIL) as code_mail, patch("central.users.frappe.sendmail") as notice:
			response = send_code(self.email)

		self.assertEqual(response, {"message": f"We sent a code to {self.email}."})
		self.assertIn("disabled", notice.call_args.kwargs["subject"])
		code_mail.assert_not_called()

	def test_a_disabled_account_and_an_unknown_email_answer_a_wrong_code_alike(self):
		frappe.set_user("Administrator")
		create_user(self.email)
		frappe.db.set_value("User", self.email, "enabled", 0)
		unknown = f"unknown.{frappe.generate_hash(length=8)}@example.test"
		self.addCleanup(EmailCode(unknown).discard)
		frappe.set_user("Guest")

		answers = []
		with patch(SENDMAIL), patch("central.users.frappe.sendmail"):
			for email in (self.email, unknown):
				send_code(email)
				with self.assertRaises(EmailCodeError) as wrong:
					verify_code(email, "000000")
				answers.append(str(wrong.exception))

		self.assertEqual(answers[0], answers[1])

	def test_an_account_disabled_after_its_code_was_sent_cannot_sign_in(self):
		frappe.set_user("Administrator")
		create_user(self.email)
		frappe.set_user("Guest")
		with patch(SENDMAIL):
			send_code(self.email)
		frappe.db.set_value("User", self.email, "enabled", 0)

		with self.assertRaises(frappe.ValidationError):
			self._verify(self._code())
		self.assertEqual(frappe.session.user, "Guest")

	def test_a_code_that_could_not_be_mailed_is_reported(self):
		with patch(SENDMAIL, side_effect=Exception("SMTP down")):
			with self.assertRaises(frappe.ValidationError) as refused:
				send_code(self.email, "Unsent")

		self.assertIn("could not send a code", str(refused.exception))
		code = EmailCode(self.email).pending["code"]
		logged = frappe.get_last_doc("Error Log", filters={"method": "Email code could not be sent"})
		self.assertIn("SMTP down", logged.error)
		self.assertNotIn(code, logged.error)

	def test_malformed_input_is_refused_before_anything_is_sent(self):
		with patch(SENDMAIL) as sendmail:
			for email in ("not-an-email", "one@example.test,two@example.test", "jane@example..com", []):
				with self.assertRaises(frappe.ValidationError):
					send_code(email)
			for name in ("   ", "x" * 141, ["list"]):
				with self.assertRaises(frappe.ValidationError):
					send_code(self.email, name)
			with self.assertRaises(frappe.ValidationError):
				verify_code(self.email, "12345x")

		sendmail.assert_not_called()

	def test_the_email_states_the_code_and_its_expiry(self):
		with patch(SENDMAIL) as sendmail:
			send_code(self.email, "Template Person")

		html = frappe.render_template(
			"templates/emails/verification_code.html", sendmail.call_args.kwargs["args"]
		)
		self.assertIn(self._code(), html)
		self.assertIn(self._code(), sendmail.call_args.kwargs["subject"])
		self.assertIn("Create your Frappe Cloud account", html)
		self.assertIn("It expires in 10 minutes.", html)

	def test_sending_is_limited_per_email_whatever_its_spelling(self):
		spellings = [self.email, self.email.upper(), f" {self.email} ", self.email.title(), self.email]
		other = f"other.{frappe.generate_hash(length=8)}@example.test"
		self.addCleanup(EmailCode(other).discard)

		with patch(SENDMAIL) as sendmail:
			for spelling in spellings:
				send_code(spelling, "Limit Test")
			with self.assertRaisesRegex(EmailCodeError, "Too many codes requested"):
				send_code(self.email.upper(), "Limit Test")
			send_code(other, "Someone Else")

		self.assertEqual(sendmail.call_count, 6)

	def test_the_hourly_signup_cap_refuses_a_new_account(self):
		with patch(SENDMAIL):
			send_code(self.email, "Over The Cap")

		with patch("central.users.frappe.db.get_creation_count", return_value=300):
			with self.assertRaises(frappe.TooManyRequestsError):
				self._verify(self._code())
		self.assertIsNotNone(EmailCode(self.email).pending)

	def test_guest_context(self):
		context = build_auth_context()

		self.assertEqual(context["user"], "Guest")
		self.assertFalse(context["onboarding_complete"])

	def _code(self) -> str:
		return EmailCode(self.email).pending["code"]

	def _verify(self, code: str, full_name: str | None = None) -> dict:
		with patch("frappe.local.login_manager", create=True) as login_manager:
			login_manager.login_as.side_effect = frappe.set_user
			return verify_code(self.email, code, full_name)
