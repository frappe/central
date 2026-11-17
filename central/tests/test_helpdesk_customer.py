from __future__ import annotations

from unittest.mock import call, patch

import frappe

from central.support import assign_marked_tickets, get_customer_contacts, team_context_line
from central.tests.test_iam import ensure_user
from central.tests.test_support import SupportTestCase


class TestHelpdeskCustomerSync(SupportTestCase):
	def test_customer_contacts_name_active_members_and_their_manager_flag(self):
		developer = ensure_user("support.developer@example.test")
		invited = ensure_user("support.invited@example.test")
		self._add_member(developer, "Developer")
		self._add_member(invited, "Developer", status="Invited")
		viewer = ensure_user("support.viewer@example.test")
		self._add_member(viewer, "Viewer")

		contacts = {contact["email"]: contact for contact in get_customer_contacts(self.team)}

		self.assertTrue(contacts[self.owner]["is_manager"])
		self.assertEqual(
			contacts[self.owner]["full_name"], frappe.db.get_value("User", self.owner, "full_name")
		)
		self.assertTrue(contacts[developer]["is_manager"])
		self.assertFalse(contacts[viewer]["is_manager"])
		self.assertNotIn(invited, contacts)

	def test_a_member_change_enqueues_one_helpdesk_customer_sync(self):
		member = ensure_user("support.member@example.test")
		self.enterContext(patch("central.support.is_helpdesk_configured", return_value=True))
		enqueue = self.enterContext(patch("frappe.enqueue"))

		self._add_member(member, "Developer")

		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.args[0], "central.support.sync_helpdesk_customer")
		self.assertEqual(enqueue.call_args.kwargs["team"], self.team)

	def test_a_team_status_change_enqueues_a_sync(self):
		self.enterContext(patch("central.support.is_helpdesk_configured", return_value=True))
		enqueue = self.enterContext(patch("frappe.enqueue"))
		team = frappe.get_doc("Team", self.team)
		team.status = "Suspended"

		team.save()

		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.kwargs["team"], self.team)

	def test_a_team_save_without_a_member_change_enqueues_no_sync(self):
		self.enterContext(patch("central.support.is_helpdesk_configured", return_value=True))
		enqueue = self.enterContext(patch("frappe.enqueue"))
		team = frappe.get_doc("Team", self.team)
		team.team_name = f"Renamed {self.suffix}"

		team.save()

		enqueue.assert_not_called()

	def test_a_custom_role_capability_change_syncs_its_team(self):
		role = frappe.get_doc("Team Role", self._custom_role("support:view"))
		self.enterContext(patch("central.support.is_helpdesk_configured", return_value=True))
		enqueue = self.enterContext(patch("frappe.enqueue"))

		role.append("capabilities", {"capability": "support:manage"})
		role.save()

		synced = [
			call
			for call in enqueue.call_args_list
			if call.args[0] == "central.support.sync_helpdesk_customer"
		]
		self.assertEqual([call.kwargs["team"] for call in synced], [self.team])

	def test_the_patch_gives_custom_roles_support_view_once(self):
		from central.patches.v0_0.grant_support_view_to_custom_roles import execute

		role = self._custom_role("server:view")

		execute()
		execute()

		capabilities = frappe.get_all("Role Capability", {"parent": role}, pluck="capability")
		self.assertEqual(sorted(capabilities), ["server:view", "support:view"])

	def test_the_patch_queues_one_sync_per_team(self):
		from central.patches.v0_0.sync_helpdesk_customers import execute

		self.enterContext(patch("central.support.is_helpdesk_configured", return_value=True))
		enqueue = self.enterContext(patch("frappe.enqueue"))

		execute()

		synced = [
			call.kwargs["team"]
			for call in enqueue.call_args_list
			if call.args[0] == "central.support.sync_helpdesk_customer"
		]
		self.assertIn(self.team, synced)
		self.assertIn(self.other_team, synced)
		self.assertEqual(
			enqueue.call_args.args[0],
			"central.support.assign_marked_tickets",
		)

	def test_assign_marked_tickets_keeps_going_when_one_team_fails(self):
		self.enterContext(patch("central.support.is_helpdesk_configured", return_value=True))
		log_error = self.enterContext(patch("frappe.log_error"))
		self.customer_helpdesk.list_marked_tickets.return_value = [
			{"name": "HD-1", "description": team_context_line(self.team)},
			{"name": "HD-2", "description": team_context_line(self.team)},
			{"name": "HD-3", "description": team_context_line(self.other_team)},
			{"name": "HD-4", "description": team_context_line("TEAM-404")},
		]
		self.customer_helpdesk.set_ticket_customer.side_effect = self._failed_ticket_assignment

		assign_marked_tickets()

		self.customer_helpdesk.set_ticket_customer.assert_has_calls(
			[call(["HD-1", "HD-2"], self.team), call(["HD-3"], self.other_team)]
		)
		self.assertEqual(log_error.call_args.kwargs["title"], "Helpdesk customer backfill failed")

	def _failed_ticket_assignment(self, tickets: list[str], team: str) -> None:
		if team == self.team:
			raise RuntimeError("Helpdesk is down")
