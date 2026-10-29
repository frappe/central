from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

from central.signups.alerts import alert_failed_signups
from central.tests.test_trial_lifecycle import TrialOnAMachine


class TestSignupAlerts(TrialOnAMachine):
	"""The hourly check tells the operators about signup site creations that failed in the last hour."""

	def setUp(self):
		super().setUp()
		self.notify = self.enterContext(patch("central.signups.alerts.notify_operators"))
		self.creation = frappe.get_doc(
			"Resource Action", {"server": self.server.name, "resource_type": "Site"}
		)

	def fail(self, hours_ago: int) -> None:
		self.creation.db_set(
			{
				"status": "Failed",
				"error_code": "REGION_AT_CAPACITY",
				"error_message": "The region is full.",
				"completed_at": add_to_date(now_datetime(), hours=-hours_ago),
			}
		)

	def alerted(self) -> list[str]:
		return [row["subject"] for call in self.notify.call_args_list for row in call.args[1]]

	def test_a_failure_in_the_last_hour_is_alerted(self):
		self.fail(hours_ago=0)

		alert_failed_signups()

		self.notify.assert_called_once()
		self.assertIn("Signup failures in the last hour", self.notify.call_args.args[0])
		self.assertIn(self.creation.name, self.alerted())

	def test_an_older_failure_is_not_alerted(self):
		self.fail(hours_ago=2)

		alert_failed_signups()

		self.assertNotIn(self.creation.name, self.alerted())
