import frappe
from frappe.tests import IntegrationTestCase

from central.api.integrations.insights import hold_app_releases
from central.central.doctype.app_rollout_hold.app_rollout_hold import AppRolloutHold
from central.central.doctype.app_rollout_hold.test_app_rollout_hold import failing_row
from central.iam import APP_ROLLOUT_ALERT_ROLE
from central.tests.test_iam import ensure_user
from central.users import CENTRAL_USER_ROLE


def make_alert_user(email: str) -> str:
	user = frappe.get_doc("User", ensure_user(email))
	user.remove_roles(CENTRAL_USER_ROLE)
	user.add_roles(APP_ROLLOUT_ALERT_ROLE)
	return email


class TestAppRolloutAlert(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		frappe.db.delete("App Rollout Hold")

	def get_holds(self) -> list[str]:
		return AppRolloutHold.get_held_commits()

	def test_a_user_without_the_role_cannot_hold_a_release(self):
		frappe.set_user(ensure_user("alert.denied@example.test"))
		with self.assertRaises(frappe.PermissionError):
			hold_app_releases({"rows": [failing_row("abc")]})

		frappe.set_user("Administrator")
		self.assertEqual(self.get_holds(), [])

	def test_a_user_with_the_role_holds_the_rows(self):
		frappe.set_user(make_alert_user("alert.allowed@example.test"))
		hold_app_releases({"rows": [failing_row("abc")]})

		frappe.set_user("Administrator")
		self.assertEqual(self.get_holds(), ["abc"])

	def test_the_alert_user_cannot_create_a_hold_directly(self):
		frappe.set_user(make_alert_user("alert.direct@example.test"))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{"doctype": "App Rollout Hold", "app": "erpnext", "commit": "abc", "released": 1}
			).insert()

	def test_no_rows_hold_nothing_and_missing_rows_fail(self):
		frappe.set_user(make_alert_user("alert.empty@example.test"))
		hold_app_releases({"rows": []})
		with self.assertRaises(frappe.ValidationError):
			hold_app_releases({})

		frappe.set_user("Administrator")
		self.assertEqual(self.get_holds(), [])

	def test_a_new_alert_user_does_not_get_the_central_user_role(self):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": "alert.new@example.test",
				"first_name": "Alert",
				"send_welcome_email": 0,
				"roles": [{"role": APP_ROLLOUT_ALERT_ROLE}],
			}
		).insert()

		self.assertNotIn(CENTRAL_USER_ROLE, frappe.get_roles(user.name))

	def test_the_alert_user_cannot_also_be_a_central_user(self):
		user = frappe.get_doc("User", ensure_user("alert.both@example.test"))
		with self.assertRaises(frappe.ValidationError):
			user.add_roles(APP_ROLLOUT_ALERT_ROLE)
