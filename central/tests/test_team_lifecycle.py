from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, get_first_day, today

from central.api.identity import my_teams
from central.api.teams import (
	archive_team,
	get_team_archive_checks,
	impersonate_team_owner,
	invite_team_member,
	restore_team,
	suspend_team,
	unsuspend_team,
)
from central.iam import can
from central.services.ai import stop_team_keys
from central.services.doctype.team_service.team_service import STORAGE_SERVICE
from central.tests.test_team_management import create_user
from central.tests.utils import ensure_server


class TestTeamLifecycle(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = create_user("archive.owner@example.test")
		self.admin = create_user("archive.admin@example.test")
		self.operator = create_user("archive.operator@example.test")
		frappe.get_doc("User", self.operator).add_roles("System Manager")
		self.team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Closing Team",
				"owner_user": self.owner,
				"members": [
					{"user": self.owner, "role": "Owner", "status": "Active"},
					{"user": self.admin, "role": "Admin", "status": "Active"},
				],
			}
		).insert()

		sendmail = patch("central.identity.doctype.team_invitation.team_invitation.frappe.sendmail")
		sendmail.start()
		self.addCleanup(sendmail.stop)

	def tearDown(self):
		frappe.set_user("Administrator")

	def blockers(self) -> dict[str, int]:
		frappe.set_user(self.owner)
		return {check["key"]: check["count"] for check in get_team_archive_checks(self.team.name)["checks"]}

	def add_invoice(self, status: str, period_end: str, total: float = 0) -> None:
		frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": self.team.name,
				"invoice_type": "Billable",
				"status": status,
				"period_end": period_end,
				"total": total,
			}
		).db_insert()

	def add_subscription(self, **fields) -> None:
		frappe.get_doc(
			{"doctype": "Subscription", "team": self.team.name, "enabled": 1, **fields}
		).db_insert()

	def test_the_owner_archives_a_clear_team_and_members_lose_access(self):
		frappe.set_user(self.owner)
		invitation = invite_team_member(self.team.name, "archive.invitee@example.test", "Viewer")

		with (
			patch("central.services.ai.stop_team_keys") as stop_team_keys,
			patch("central.notification.engine.dispatch") as dispatch,
		):
			archive_team(self.team.name)

		stop_team_keys.assert_called_once_with(self.team.name)
		dispatch.assert_called_once_with(self.team.name, "team_archived", affected_user=self.owner)
		self.assertEqual(frappe.db.get_value("Team", self.team.name, "status"), "Archived")
		self.assertEqual(frappe.db.get_value("Team Invitation", invitation, "status"), "Revoked")
		self.assertFalse(can(self.admin, self.team.name, "team:edit"))
		self.assertNotIn(self.team.name, [team["name"] for team in my_teams()])
		self.assertTrue(
			frappe.db.exists("Comment", {"reference_name": self.team.name, "content": ("like", "%archived%")})
		)

	def test_only_the_owner_can_archive(self):
		frappe.set_user(self.admin)
		with self.assertRaises(frappe.PermissionError):
			archive_team(self.team.name)
		with self.assertRaises(frappe.PermissionError):
			get_team_archive_checks(self.team.name)

	def test_a_live_server_blocks_and_a_terminated_one_does_not(self):
		server = ensure_server("archive-srv", self.team.name)
		self.assertEqual(self.blockers()["servers"], 1)
		with self.assertRaises(frappe.ValidationError):
			archive_team(self.team.name)

		frappe.db.set_value("Virtual Machine", server, "status", "Terminated")
		self.assertEqual(self.blockers()["servers"], 0)

	def test_each_kind_of_billing_add_on_blocks_on_its_own_row(self):
		self.add_subscription(vm_snapshot="archive-snapshot")
		self.add_subscription(service_subject="storage:archive-region")
		self.add_subscription(service_subject="storage:archive-other")
		self.add_subscription()
		self.add_subscription(enabled=0)

		blockers = self.blockers()
		self.assertEqual((blockers["snapshots"], blockers["buckets"], blockers["add_ons"]), (1, 2, 1))

	def test_unpaid_invoices_block_but_the_current_month_draft_does_not(self):
		self.add_invoice("Draft", today())
		self.add_invoice("Paid", add_months(today(), -2))
		self.assertEqual(self.blockers()["invoices"], 0)

		self.add_invoice("Overdue", add_months(today(), -1))
		self.add_invoice("Draft", add_months(get_first_day(today()), -1))
		self.assertEqual(self.blockers()["invoices"], 2)

	def test_this_months_charges_block_until_the_team_has_a_payment_method(self):
		self.add_invoice("Draft", today())
		self.assertEqual(self.blockers()["final_bill"], 0)

		self.add_invoice("Draft", today(), total=120)
		self.assertEqual(self.blockers()["final_bill"], 1)

		frappe.get_doc({"doctype": "Payment Method", "team": self.team.name, "status": "Active"}).db_insert()
		self.assertEqual(self.blockers()["final_bill"], 0)

	def test_the_checks_report_the_credit_that_archiving_forfeits(self):
		frappe.get_doc(
			{
				"doctype": "Credit Wallet",
				"name": f"{self.team.name}-USD",
				"team": self.team.name,
				"currency": "USD",
				"balance": 25,
			}
		).db_insert()

		frappe.set_user(self.owner)
		balances = get_team_archive_checks(self.team.name)["credit_balances"]
		self.assertEqual([(row.currency, row.balance) for row in balances], [("USD", 25)])

	def test_an_operator_restores_an_archived_team(self):
		frappe.set_user(self.owner)
		with patch("central.services.ai.stop_team_keys"), patch("central.notification.engine.dispatch"):
			archive_team(self.team.name)
		with self.assertRaises(frappe.PermissionError):
			restore_team(self.team.name)

		frappe.set_user(self.operator)
		restore_team(self.team.name)
		self.assertEqual(frappe.db.get_value("Team", self.team.name, "status"), "Active")
		self.assertTrue(can(self.admin, self.team.name, "team:edit"))

	def test_archive_stops_every_live_ai_key_and_revokes_the_old_ones(self):
		keys = [
			{"name": "old-key", "status": "active", "revocable_at": "2020-01-01T00:00:00Z"},
			{"name": "new-key", "status": "active", "revocable_at": "2999-01-01T00:00:00Z"},
			{"name": "gone-key", "status": "revoked", "revocable_at": "2020-01-01T00:00:00Z"},
		]
		client = MagicMock()
		client.get_figures.return_value = {"keys": keys}
		with (
			patch("central.services.ai.get_ai_service", return_value="AI-SERVICE"),
			patch("central.services.ai.GroveClient.from_settings", return_value=client),
		):
			stop_team_keys(self.team.name)

		client.update_caps.assert_called_once_with(self.team.name, {"old-key": 0, "new-key": 0})
		client.revoke_key.assert_called_once_with(self.team.name, "old-key")

	def test_a_member_cannot_change_the_status_by_saving_the_team(self):
		frappe.set_user(self.owner)
		team = frappe.get_doc("Team", self.team.name)
		team.status = "Archived"
		with self.assertRaises(frappe.PermissionError):
			team.save()

	def test_an_operator_opens_the_console_as_the_team_without_an_email(self):
		frappe.set_user(self.operator)
		with patch("central.notification.engine.dispatch") as dispatch:
			url = impersonate_team_owner(self.team.name, "Customer asked for help with DNS")["url"]

		self.assertTrue(url.endswith(f"view_as={self.team.name}"))
		dispatch.assert_not_called()
		self.assertTrue(
			frappe.db.exists(
				"Comment",
				{"reference_name": self.team.name, "content": ("like", "%Customer asked for help%")},
			)
		)
		team = next(team for team in my_teams(view_as=self.team.name) if team["name"] == self.team.name)
		self.assertTrue(team["is_impersonated"])

	def test_an_operator_can_email_the_owner_but_must_give_a_reason(self):
		frappe.set_user(self.operator)
		with self.assertRaises(frappe.ValidationError):
			impersonate_team_owner(self.team.name, "  ")

		with patch("central.notification.engine.dispatch") as dispatch:
			impersonate_team_owner(self.team.name, "Customer asked for help", notify_owner=1)

		dispatch.assert_called_once_with(self.team.name, "team_impersonated", affected_user=self.owner)
		self.assertTrue(
			frappe.db.exists(
				"Comment", {"reference_name": self.team.name, "content": ("like", "%and emailed them%")}
			)
		)

	def test_a_team_member_cannot_impersonate(self):
		outsider = create_user("archive.outsider@example.test")
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.PermissionError):
			impersonate_team_owner(self.team.name, "Testing")

		frappe.set_user(outsider)
		self.assertEqual(my_teams(view_as=self.team.name), [])

	def test_an_operator_suspends_a_team_and_its_servers_stop(self):
		running = ensure_server("suspend-running", self.team.name, atlas_vm_id="atlas-1")
		ensure_server("suspend-stopped", self.team.name, status="Stopped", atlas_vm_id="atlas-2")

		frappe.set_user(self.operator)
		with self.assertRaises(frappe.ValidationError):
			suspend_team(self.team.name, " ")
		bucket = frappe.get_doc(
			{
				"doctype": "Team Service",
				"name": f"{self.team.name}-bucket",
				"team": self.team.name,
				"add_on_service": STORAGE_SERVICE,
				"status": "Active",
			}
		)
		bucket.db_insert()
		with (
			patch("central.resource_actions.submit_command") as submit_command,
			patch("central.services.ai.set_team_suspended") as set_team_suspended,
			patch("central.notification.engine.dispatch") as dispatch,
			patch(
				"central.services.doctype.team_service.team_service.TeamService.rotate_credentials",
				autospec=True,
			) as rotate_credentials,
		):
			suspend_team(self.team.name, "Phishing report")

		submit_command.assert_called_once_with("stop", self.team.name, running)
		self.assertEqual([call.args[0].name for call in rotate_credentials.call_args_list], [bucket.name])
		set_team_suspended.assert_called_once_with(self.team.name, True)
		dispatch.assert_called_once_with(self.team.name, "team_suspended", affected_user=self.owner)
		self.assertEqual(frappe.db.get_value("Team", self.team.name, "status"), "Suspended")
		self.assertFalse(can(self.admin, self.team.name, "team:edit"))
		self.assertTrue(
			frappe.db.exists(
				"Comment", {"reference_name": self.team.name, "content": ("like", "%Phishing report%")}
			)
		)

		frappe.set_user(self.admin)
		listed = next(team for team in my_teams() if team["name"] == self.team.name)
		self.assertEqual(listed["status"], "Suspended")

	def test_an_operator_unsuspends_a_team_and_its_servers_stay_stopped(self):
		frappe.set_user(self.operator)
		with patch("central.services.ai.set_team_suspended"), patch("central.notification.engine.dispatch"):
			suspend_team(self.team.name, "Abuse")
		with (
			patch("central.resource_actions.submit_command") as submit_command,
			patch("central.services.ai.set_team_suspended") as set_team_suspended,
			patch("central.notification.engine.dispatch") as dispatch,
		):
			unsuspend_team(self.team.name)

		submit_command.assert_not_called()
		set_team_suspended.assert_called_once_with(self.team.name, False)
		dispatch.assert_called_once_with(self.team.name, "team_unsuspended", affected_user=self.owner)
		self.assertEqual(frappe.db.get_value("Team", self.team.name, "status"), "Active")
		self.assertTrue(can(self.admin, self.team.name, "team:edit"))

	def test_only_an_operator_can_suspend_or_unsuspend(self):
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.PermissionError):
			suspend_team(self.team.name, "Testing")
		with self.assertRaises(frappe.PermissionError):
			unsuspend_team(self.team.name)
