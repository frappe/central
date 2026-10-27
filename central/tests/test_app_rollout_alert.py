import frappe
from frappe.tests import IntegrationTestCase

from central.api.integrations.insights import ALERT_ROLE, hold_app_releases
from central.central.doctype.app_rollout_hold.app_rollout_hold import AppRolloutHold
from central.central.doctype.app_rollout_hold.test_app_rollout_hold import failing_row
from central.tests.test_iam import ensure_user


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
		user = ensure_user("alert.allowed@example.test")
		frappe.get_doc("User", user).add_roles(ALERT_ROLE)
		frappe.set_user(user)
		hold_app_releases({"rows": [failing_row("abc")]})

		frappe.set_user("Administrator")
		self.assertEqual(self.get_holds(), ["abc"])

	def test_no_rows_hold_nothing_and_missing_rows_fail(self):
		user = ensure_user("alert.empty@example.test")
		frappe.get_doc("User", user).add_roles(ALERT_ROLE)
		frappe.set_user(user)
		hold_app_releases({"rows": []})
		with self.assertRaises(frappe.ValidationError):
			hold_app_releases({})

		frappe.set_user("Administrator")
		self.assertEqual(self.get_holds(), [])
