from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_months, now_datetime, today
from frappe.website.doctype.personal_data_deletion_request.personal_data_deletion_request import (
	process_data_deletion_request,
)

from central.api.identity import cancel_account_deletion, delete_account, get_account_deletion
from central.api.teams import invite_team_member
from central.iam import get_user_team_names
from central.tests.test_team_management import create_user
from central.tests.utils import ensure_server


class TestAccountDeletion(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("Website Settings", "auto_account_deletion", 72)
		self.user = create_user("leaving.user@example.test")
		self.teammate = create_user("leaving.teammate@example.test")
		self.other_owner = create_user("leaving.other@example.test")
		self.own_team = self.make_team("Leaving Own", self.user)
		self.other_team = self.make_team(
			"Leaving Other", self.other_owner, [(self.user, "Admin"), (self.teammate, "Admin")]
		)

		for target in (
			"frappe.sendmail",
			"central.services.ai.stop_team_keys",
			"central.notification.engine.dispatch",
		):
			patcher = patch(target)
			patcher.start()
			self.addCleanup(patcher.stop)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def make_team(self, name: str, owner: str, members: list[tuple[str, str]] = ()) -> str:
		rows = [{"user": owner, "role": "Owner", "status": "Active"}]
		rows += [{"user": user, "role": role, "status": "Active"} for user, role in members]
		return (
			frappe.get_doc({"doctype": "Team", "team_name": name, "owner_user": owner, "members": rows})
			.insert()
			.name
		)

	def failed_checks(self) -> dict[str, int]:
		frappe.set_user(self.user)
		(team,) = get_account_deletion()["teams"]
		return {check["key"]: check["count"] for check in team["checks"] if not check["passed"]}

	def request_deletion(self) -> frappe.Document:
		frappe.set_user(self.user)
		open_request = delete_account(self.user)["request"]
		self.assertIsNotNone(open_request["delete_after"])
		name = open_request["name"]
		frappe.set_user("Administrator")
		request = frappe.get_doc("Personal Data Deletion Request", name)
		request.db_set("status", "Pending Approval")  # what the email link does
		return request

	def test_a_live_server_or_another_member_blocks_the_request(self):
		server = ensure_server("leaving-srv", self.own_team)
		self.assertEqual(self.failed_checks(), {"servers": 1})
		with self.assertRaises(frappe.ValidationError):
			delete_account(self.user)

		frappe.db.set_value("Virtual Machine", server, "status", "Terminated")
		frappe.set_user("Administrator")
		team = frappe.get_doc("Team", self.own_team)
		team.append("members", {"user": self.teammate, "role": "Admin", "status": "Active"})
		team.save()
		self.assertEqual(self.failed_checks(), {"members": 1})
		with self.assertRaises(frappe.ValidationError):
			delete_account(self.user)

	def test_the_typed_email_must_be_the_users_own(self):
		frappe.set_user(self.user)
		for typed in ("", self.teammate):
			with self.assertRaises(frappe.ValidationError):
				delete_account(typed)
		self.assertIsNone(get_account_deletion()["request"])

	def test_a_confirmed_request_deletes_the_account_and_keeps_other_teams(self):
		third_team = self.make_team("Leaving Third", self.other_owner)
		frappe.set_user(self.other_owner)
		invitation = invite_team_member(third_team, self.user, "Viewer")
		request = self.request_deletion()

		request.trigger_data_deletion()

		self.assertEqual(frappe.db.get_value("Team", self.own_team, "status"), "Archived")
		self.assertEqual(frappe.db.get_value("Team", self.other_team, "status"), "Active")
		self.assertEqual(get_user_team_names(self.teammate), [self.other_team])
		self.assertFalse(frappe.db.exists("User", self.user))
		self.assertEqual(frappe.db.get_value("User", request.name, "enabled"), 0)
		self.assertFalse(frappe.db.exists("Team Member", {"user": request.name, "parent": self.other_team}))
		self.assertEqual(frappe.db.get_value("Team Invitation", invitation, "email"), request.name)
		self.assertEqual(
			frappe.db.get_value("Personal Data Deletion Request", request.name, "status"), "Deleted"
		)

	def test_a_server_added_while_waiting_holds_the_request(self):
		request = self.request_deletion()
		ensure_server("leaving-late-srv", self.own_team)

		request.trigger_data_deletion()

		self.assertEqual(request.status, "On Hold")
		self.assertEqual(frappe.db.get_value("User", self.user, "enabled"), 1)
		self.assertEqual(frappe.db.get_value("Team", self.own_team, "status"), "Active")

	def test_the_user_cancels_while_waiting(self):
		request = self.request_deletion()
		second = frappe.get_doc(
			{"doctype": "Personal Data Deletion Request", "email": self.user, "status": "Pending Approval"}
		)
		second.set_new_name()
		second.db_insert()
		frappe.set_user(self.user)

		cancel_account_deletion()

		self.assertIsNone(get_account_deletion()["request"])
		for name in (request.name, second.name):
			self.assertEqual(frappe.db.get_value("Personal Data Deletion Request", name, "status"), "On Hold")
		with self.assertRaises(frappe.ValidationError):
			cancel_account_deletion()

	def test_a_second_request_for_the_same_user_is_refused(self):
		self.request_deletion()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Personal Data Deletion Request", "email": self.user}).insert()

	def test_a_request_for_a_user_that_is_gone_is_held(self):
		request = self.request_deletion()
		frappe.db.delete("User", self.user)

		request.trigger_data_deletion()

		self.assertEqual(
			frappe.db.get_value("Personal Data Deletion Request", request.name, "status"), "On Hold"
		)

	def test_a_suspended_team_blocks_the_request(self):
		frappe.db.set_value("Team", self.own_team, "status", "Suspended")
		self.assertEqual(self.failed_checks(), {"suspended": 1})
		with self.assertRaises(frappe.ValidationError):
			delete_account(self.user)

	def test_only_the_system_runs_the_deletion(self):
		request = self.request_deletion()
		frappe.set_user(self.user)
		with self.assertRaises(frappe.PermissionError):
			request.trigger_data_deletion()
		self.assertEqual(frappe.db.get_value("Team", self.own_team, "status"), "Active")

	def test_an_unpaid_invoice_blocks_and_the_paid_invoice_is_kept(self):
		invoice = frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": self.own_team,
				"invoice_type": "Billable",
				"status": "Overdue",
				"period_end": add_months(today(), -1),
				"due_date": add_months(today(), -1),
				"total": 40,
			}
		)
		invoice.db_insert()
		self.assertEqual(self.failed_checks(), {"invoices": 1})
		with self.assertRaises(frappe.ValidationError):
			delete_account(self.user)

		frappe.db.set_value("Invoice", invoice.name, "status", "Paid")
		self.request_deletion().trigger_data_deletion()

		kept = frappe.db.get_value("Invoice", invoice.name, ["team", "status", "total"], as_dict=True)
		self.assertEqual((kept.team, kept.status, kept.total), (self.own_team, "Paid", 40))

	def test_the_hourly_job_deletes_only_after_the_waiting_period(self):
		request = self.request_deletion()

		process_data_deletion_request()
		self.assertTrue(frappe.db.exists("User", self.user))

		request.db_set("creation", add_days(now_datetime(), -4))
		process_data_deletion_request()
		self.assertFalse(frappe.db.exists("User", self.user))
		self.assertEqual(
			frappe.db.get_value("Personal Data Deletion Request", request.name, "status"), "Deleted"
		)
