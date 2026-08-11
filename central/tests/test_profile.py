import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today
from frappe.utils.password import check_password, update_password

from central.api.auth import change_password
from central.api.identity import my_profile, update_profile

OLD_PASSWORD = "OldPass@12345"
NEW_PASSWORD = "NewPass@67890"


class TestProfile(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.user = "profile.user@example.test"
		if not frappe.db.exists("User", self.user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": self.user,
					"first_name": "Profile User",
					"enabled": 1,
					"send_welcome_email": 0,
				}
			).insert()
		update_password(self.user, OLD_PASSWORD)
		frappe.set_user(self.user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_my_profile_returns_the_session_user(self):
		profile = my_profile()
		self.assertEqual(profile["user"], self.user)
		self.assertEqual(profile["full_name"], "Profile User")

	def test_guest_is_rejected(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			my_profile()
		with self.assertRaises(frappe.PermissionError):
			change_password(OLD_PASSWORD, NEW_PASSWORD)

	def test_update_profile_escapes_html(self):
		# Same write-time escaping as the signup path: full_name reaches HTML
		# contexts outside the SPA (frappe emails, desk).
		result = update_profile("North<b>wind</b>")
		self.assertNotIn("<b>", result["full_name"])
		self.assertIn("&lt;b&gt;", frappe.db.get_value("User", self.user, "first_name"))

	def test_update_profile_rejects_empty(self):
		with self.assertRaises(frappe.ValidationError):
			update_profile("   ")

	# ── change_password ──

	def test_wrong_current_password_is_a_validation_error(self):
		# The regression this guards: AuthenticationError here makes frappe's
		# request handler treat the call as a failed login and tear down the
		# session — a typo would sign the user out of the console.
		with self.assertRaises(frappe.ValidationError) as caught:
			change_password("not-the-password", NEW_PASSWORD)
		self.assertNotIsInstance(caught.exception, frappe.AuthenticationError)

	def test_reusing_the_current_password_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			change_password(OLD_PASSWORD, OLD_PASSWORD)

	def test_weak_new_password_fails_the_site_policy(self):
		# Written directly, not via change_settings: that saves the whole
		# System Settings doc, and a fresh CI site (no setup wizard) fails its
		# language/time_zone mandatory validation on save.
		for field, value in (("enable_password_policy", 1), ("minimum_password_score", 2)):
			original = frappe.db.get_single_value("System Settings", field)
			frappe.db.set_single_value("System Settings", field, value)
			self.addCleanup(frappe.db.set_single_value, "System Settings", field, original or 0)

		with self.assertRaises(frappe.ValidationError):
			change_password(OLD_PASSWORD, "12345678")

	def test_valid_change_updates_the_password(self):
		result = change_password(OLD_PASSWORD, NEW_PASSWORD)
		self.assertTrue(result["changed"])
		# The new password authenticates; the old one no longer does.
		check_password(self.user, NEW_PASSWORD)
		with self.assertRaises(frappe.AuthenticationError):
			check_password(self.user, OLD_PASSWORD)
		self.assertEqual(str(frappe.db.get_value("User", self.user, "last_password_reset_date")), today())
