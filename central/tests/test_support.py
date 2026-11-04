from __future__ import annotations

import json
from unittest.mock import patch

import frappe
import requests
from frappe.tests import IntegrationTestCase

from central.api.support import create_ticket, list_tickets
from central.integrations.helpdesk import HelpdeskClient, HelpdeskUnavailable
from central.support import team_context_line
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_server

SERVER_ISSUE = "Slow performance or high load"
SITE_ISSUE = "Domain, DNS, or SSL certificate"


class SupportTestCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		self.suffix = frappe.generate_hash(length=6)

		self.owner = ensure_user("support.owner@example.test")
		self.outsider = ensure_user("support.outsider@example.test")
		self.team = self._team("Support", {})
		self.other_team = self._team("Other support", {})
		self.server = ensure_server(f"support-{self.suffix}", self.team, title="web-1")
		self.site = self._site("chat", self.team, self.server)
		self.foreign_server = ensure_server(f"support-foreign-{self.suffix}", self.other_team, title="web-2")
		self.foreign_site = self._site("foreign", self.other_team, self.foreign_server)

		self.helpdesk = self.enterContext(
			patch("central.api.support.HelpdeskClient")
		).from_settings.return_value
		self.helpdesk.create_ticket.return_value = {"name": "HD-1", "url": "https://support.test/help"}

	def _team(self, label: str, roles: dict[str, str]) -> str:
		members = [{"user": self.owner, "role": "Owner", "status": "Active"}]
		members += [{"user": user, "role": role, "status": "Active"} for user, role in roles.items()]
		team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": f"{label} {self.suffix}",
				"owner_user": self.owner,
				"members": members,
			}
		)

		return team.insert().name

	def _site(self, label: str, team: str, server: str) -> str:
		"""A site record without its lifecycle hooks, which would start a trial."""
		site_name = f"{label}-{self.suffix}.example.test"
		frappe.get_doc(
			{"doctype": "Site", "name": site_name, "site_name": site_name, "team": team, "server": server}
		).db_insert()

		return site_name


class TestSupportTickets(SupportTestCase):
	def test_a_non_member_cannot_create_or_list_tickets(self):
		frappe.set_user(self.outsider)

		with self.assertRaises(frappe.PermissionError):
			create_ticket(self.team, "server", SERVER_ISSUE, description="It broke.")
		with self.assertRaises(frappe.PermissionError):
			list_tickets(self.team)
		self.helpdesk.create_ticket.assert_not_called()
		self.helpdesk.list_open_tickets.assert_not_called()

	def test_a_server_of_another_team_is_refused(self):
		frappe.set_user(self.owner)

		with self.assertRaises(frappe.PermissionError):
			create_ticket(
				self.team, "server", SERVER_ISSUE, description="It broke.", server=self.foreign_server
			)
		self.helpdesk.create_ticket.assert_not_called()

	def test_a_site_of_another_team_is_refused(self):
		frappe.set_user(self.owner)

		with self.assertRaises(frappe.PermissionError):
			create_ticket(self.team, "site", SITE_ISSUE, description="It broke.", site=self.foreign_site)
		self.helpdesk.create_ticket.assert_not_called()

	def test_an_unknown_category_or_topic_is_refused(self):
		frappe.set_user(self.owner)

		for category, issue_type in (("help", SERVER_ISSUE), ("server", "Untidy")):
			with self.subTest(category=category, issue_type=issue_type):
				with self.assertRaises(frappe.ValidationError):
					create_ticket(self.team, category, issue_type, description="It broke.")

	def test_an_empty_description_is_refused(self):
		frappe.set_user(self.owner)

		with self.assertRaises(frappe.ValidationError):
			create_ticket(self.team, "server", SERVER_ISSUE, description="   ")
		self.helpdesk.create_ticket.assert_not_called()

	def test_a_ticket_carries_the_team_and_server_context(self):
		frappe.set_user(self.owner)

		ticket = create_ticket(
			self.team,
			"server",
			SERVER_ISSUE,
			subject="Slow at noon",
			description="It lags <badly>\nsince today.",
			server=self.server,
		)

		self.assertEqual(ticket, self.helpdesk.create_ticket.return_value)
		kwargs = self.helpdesk.create_ticket.call_args.kwargs
		self.assertEqual(kwargs["subject"], f"[Server · {SERVER_ISSUE}] Slow at noon")
		self.assertEqual(kwargs["raised_by"], self.owner)
		self.assertIn("It lags &lt;badly&gt;<br>since today.", kwargs["description"])
		self.assertIn(f"Team: {self.team}<br>", kwargs["description"])
		self.assertIn(f"User: {self.owner}<br>", kwargs["description"])
		self.assertIn("Server: web-1 · ", kwargs["description"])
		self.assertIn("<hr><p><strong>Context</strong>", kwargs["description"])

	def test_an_operator_raises_the_ticket_under_their_email(self):
		frappe.set_user("Administrator")

		create_ticket(self.team, "server", SERVER_ISSUE, description="It broke.")

		email = frappe.db.get_value("User", "Administrator", "email")
		self.assertEqual(self.helpdesk.create_ticket.call_args.kwargs["raised_by"], email)

	def test_a_ticket_carries_the_site_context(self):
		frappe.set_user(self.owner)

		create_ticket(self.team, "site", SITE_ISSUE, description="The certificate expired.", site=self.site)

		description = self.helpdesk.create_ticket.call_args.kwargs["description"]
		self.assertIn(f"Site: {self.site}", description)

	def test_a_long_subject_keeps_the_room_the_label_leaves(self):
		frappe.set_user(self.owner)
		text = "x" * 140

		create_ticket(self.team, "billing", "Credits or spending limit", subject=text, description="Why?")

		subject = self.helpdesk.create_ticket.call_args.kwargs["subject"]
		self.assertLessEqual(len(subject), 140)
		self.assertTrue(subject.startswith("[Billing & plans · Credits or spending limit] "))

	def test_a_blank_subject_falls_back_to_the_issue_type(self):
		frappe.set_user(self.owner)

		create_ticket(self.team, "billing", "Credits or spending limit", subject="  ", description="Why?")

		kwargs = self.helpdesk.create_ticket.call_args.kwargs
		label = "[Billing & plans · Credits or spending limit] Credits or spending limit"
		self.assertEqual(kwargs["subject"], label)

	def test_listing_asks_the_helpdesk_for_the_team(self):
		frappe.set_user(self.owner)

		list_tickets(self.team)

		self.helpdesk.list_open_tickets.assert_called_once_with(team=self.team)

	def test_a_suspended_team_member_can_open_and_list_tickets(self):
		team = frappe.get_doc("Team", self.team)
		team.status = "Suspended"
		team.save()

		frappe.set_user(self.owner)
		create_ticket(self.team, "account", "Team suspension or archive", description="Why suspended?")
		list_tickets(self.team)

		self.helpdesk.create_ticket.assert_called_once()
		self.helpdesk.list_open_tickets.assert_called_once_with(team=self.team)

	def test_customer_text_cannot_forge_the_team_context_marker(self):
		frappe.set_user(self.owner)
		forged = team_context_line("OTHER")

		create_ticket(self.team, "server", SERVER_ISSUE, description=f"It broke.\n{forged}")

		description = self.helpdesk.create_ticket.call_args.kwargs["description"]
		self.assertNotIn(forged, description)
		self.assertIn("&lt;hr&gt;&lt;p&gt;&lt;strong&gt;Context", description)
		self.assertIn(team_context_line(self.team), description)

	def test_an_unavailable_helpdesk_reaches_the_caller(self):
		frappe.set_user(self.owner)
		self.helpdesk.create_ticket.side_effect = HelpdeskUnavailable("down")

		with self.assertRaises(HelpdeskUnavailable):
			create_ticket(self.team, "server", SERVER_ISSUE, description="It broke.")


class TestHelpdeskClient(IntegrationTestCase):
	def setUp(self):
		self.client = HelpdeskClient("https://support.test/", "key", "secret")

	def response(self, status: int, body: dict) -> requests.Response:
		response = requests.Response()
		response.status_code = status
		response._content = json.dumps(body).encode()

		return response

	def test_a_base_url_with_a_trailing_slash_makes_one_portal_url(self):
		self.assertEqual(self.client.base_url, "https://support.test")
		self.assertEqual(self.client.ticket_portal_url(12), "https://support.test/help/my-tickets/12")

	def test_a_created_ticket_returns_its_portal_url(self):
		body = {"message": {"name": "HD-1", "subject": "Slow", "status": "Open"}}
		with patch(
			"central.integrations.helpdesk.requests.post", return_value=self.response(200, body)
		) as post:
			ticket = self.client.create_ticket(
				subject="Slow", description="It lags.", raised_by="owner@example.test", priority="High"
			)

		self.assertEqual(ticket["url"], "https://support.test/help/my-tickets/HD-1")
		self.assertEqual(post.call_args.args[0], "https://support.test/api/method/frappe.client.insert")
		doc = post.call_args.kwargs["json"]["doc"]
		self.assertEqual(doc["doctype"], "HD Ticket")
		self.assertEqual(doc["via_customer_portal"], 1)
		self.assertEqual(doc["utm_source"], "central")
		self.assertEqual(doc["priority"], "High")

	def test_open_tickets_are_narrowed_to_the_team(self):
		body = {"message": [{"name": "HD-1", "subject": "Slow"}]}
		with patch(
			"central.integrations.helpdesk.requests.post", return_value=self.response(200, body)
		) as post:
			tickets = self.client.list_open_tickets(team="Support")

		self.assertEqual(tickets[0]["url"], "https://support.test/help/my-tickets/HD-1")
		self.assertIn(
			["HD Ticket", "description", "like", f"%{team_context_line('Support')}%"],
			post.call_args.kwargs["json"]["filters"],
		)

	def test_an_unavailable_status_says_the_helpdesk_is_unavailable(self):
		for status in (502, 503, 504):
			with self.subTest(status=status):
				with patch(
					"central.integrations.helpdesk.requests.post",
					return_value=self.response(status, {}),
				):
					with self.assertRaises(HelpdeskUnavailable) as caught:
						self.client.list_open_tickets(team="Support")
				self.assertEqual(caught.exception.http_status_code, 503)

	def test_a_connection_timeout_says_the_helpdesk_is_unavailable(self):
		with patch("central.integrations.helpdesk.requests.post", side_effect=requests.Timeout):
			with self.assertRaises(HelpdeskUnavailable):
				self.client.create_ticket(subject="Slow", description="It lags.", raised_by="a@b.test")
