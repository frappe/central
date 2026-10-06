import frappe
from frappe.tests import IntegrationTestCase

from central.api.identity import my_profile, set_profile_photo, update_profile
from central.tests.utils import upload_test_image


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

	def test_update_profile_escapes_html(self):
		# Same write-time escaping as the signup path: full_name reaches HTML
		# contexts outside the SPA (frappe emails, desk).
		result = update_profile("North<b>wind</b>")
		self.assertNotIn("<b>", result["full_name"])
		self.assertIn("&lt;b&gt;", frappe.db.get_value("User", self.user, "first_name"))

	def test_photo_is_set_from_an_upload_and_cleared(self):
		file_url = upload_test_image("User", self.user, "user_image")

		self.assertEqual(set_profile_photo(file_url)["user_image"], file_url)
		self.assertEqual(frappe.db.get_value("User", self.user, "user_image"), file_url)
		self.assertIsNone(set_profile_photo(None)["user_image"])

	def test_photo_refuses_a_file_not_uploaded_to_the_users_photo(self):
		frappe.set_user("Administrator")
		other_file = upload_test_image("User", "Administrator", "user_image")
		frappe.set_user(self.user)

		for file_url in (other_file, "https://example.com/tracker.png"):
			with self.assertRaises(frappe.ValidationError):
				set_profile_photo(file_url)

	def test_update_profile_rejects_empty(self):
		with self.assertRaises(frappe.ValidationError):
			update_profile("   ")

	def test_non_string_input_is_a_validation_error(self):
		# A JSON body can put a list or a dict where a string is expected; that has
		# to come back as a controlled error, not an unhandled server error.
		for value in ([], {"a": 1}, None):
			with self.assertRaises(frappe.ValidationError):
				update_profile(value)
