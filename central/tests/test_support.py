from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.support import create_ticket, find_related, get_ticket_options, list_tickets
from central.integrations.helpdesk import HelpdeskUnavailable
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
		frappe.db.set_single_value("Central Settings", "articles_enabled", 1)
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

	def test_a_ticket_context_links_to_the_team_and_the_server(self):
		frappe.set_user(self.owner)

		create_ticket(self.team, "server", SERVER_ISSUE, description="It broke.", server=self.server)

		description = self.helpdesk.create_ticket.call_args.kwargs["description"]
		base = frappe.utils.get_url()
		self.assertIn(f'Open in Central: <a href="{base}/app/team/{self.team}">Team</a>', description)
		self.assertIn(f'<a href="{base}/app/virtual-machine/{self.server}">Server</a>', description)
		self.assertNotIn("/app/site/", description)

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
		self.assertIn(f'<a href="{frappe.utils.get_url()}/app/site/{self.site}">Site</a>', description)

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

	def test_a_suspended_team_member_without_a_team_argument_resolves_their_only_team(self):
		solo = ensure_user("support.solo@example.test")
		team = (
			frappe.get_doc(
				{
					"doctype": "Team",
					"team_name": f"Solo {self.suffix}",
					"owner_user": solo,
					"members": [{"user": solo, "role": "Owner", "status": "Active"}],
				}
			)
			.insert()
			.name
		)
		doc = frappe.get_doc("Team", team)
		doc.status = "Suspended"
		doc.save()

		frappe.set_user(solo)
		create_ticket(None, "account", "Team suspension or archive", description="Why suspended?")

		description = self.helpdesk.create_ticket.call_args.kwargs["description"]
		self.assertIn(f"Team: {team}<br>", description)

	def test_ticket_options_flag_the_critical_issues(self):
		frappe.set_user(self.owner)

		options = get_ticket_options(self.team)

		self.assertEqual([option["key"] for option in options], ["server", "site", "billing", "account"])
		server = options[0]
		self.assertEqual(server["label"], "Server")
		self.assertEqual(set(server["issues"][0]), {"label", "is_critical"})
		critical = {issue["label"] for issue in server["issues"] if issue["is_critical"]}
		self.assertEqual(critical, {"Unreachable or down"})
		billing = next(option for option in options if option["key"] == "billing")
		self.assertIn({"label": "Payment method or failed charge", "is_critical": True}, billing["issues"])

	def test_a_critical_issue_is_always_urgent(self):
		frappe.set_user(self.owner)

		create_ticket(self.team, "server", "Unreachable or down", description="Down.", priority="Low")

		self.assertEqual(self.helpdesk.create_ticket.call_args.kwargs["priority"], "Urgent")

	def test_a_non_critical_issue_keeps_the_asked_priority(self):
		frappe.set_user(self.owner)

		create_ticket(self.team, "server", SERVER_ISSUE, description="Slow.", priority="Low")

		self.assertEqual(self.helpdesk.create_ticket.call_args.kwargs["priority"], "Low")

	def test_find_related_skips_helpdesk_for_a_short_query(self):
		frappe.set_user(self.owner)

		self.assertEqual(find_related(self.team, " ab "), {"articles": [], "tickets": []})
		self.helpdesk.search_articles.assert_not_called()
		self.helpdesk.list_related_tickets.assert_not_called()

	def test_find_related_is_refused_for_a_non_member(self):
		frappe.set_user(self.outsider)

		with self.assertRaises(frappe.PermissionError):
			find_related(self.team, "broken mail")
		self.helpdesk.search_articles.assert_not_called()

	def test_find_related_asks_for_articles_and_the_team_tickets(self):
		frappe.set_user(self.owner)
		self.helpdesk.search_articles.return_value = [{"name": "kb-1"}]
		self.helpdesk.list_related_tickets.return_value = [{"name": "HD-9"}]

		result = find_related(self.team, "  broken mail ")

		self.assertEqual(result, {"articles": [{"name": "kb-1"}], "tickets": [{"name": "HD-9"}]})
		self.helpdesk.search_articles.assert_called_once_with("broken mail")
		self.helpdesk.list_related_tickets.assert_called_once_with(self.team, "broken mail")

	def test_find_related_skips_articles_when_they_are_disabled(self):
		frappe.set_user(self.owner)
		frappe.db.set_single_value("Central Settings", "articles_enabled", 0)
		self.helpdesk.list_related_tickets.return_value = [{"name": "HD-9"}]

		result = find_related(self.team, "broken mail")

		self.helpdesk.search_articles.assert_not_called()
		self.assertEqual(result, {"articles": [], "tickets": [{"name": "HD-9"}]})

	def test_find_related_keeps_tickets_when_the_articles_fail(self):
		frappe.set_user(self.owner)
		self.helpdesk.search_articles.side_effect = HelpdeskUnavailable("down")
		self.helpdesk.list_related_tickets.return_value = [{"name": "HD-9"}]

		result = find_related(self.team, "broken mail")

		self.assertEqual(result, {"articles": [], "tickets": [{"name": "HD-9"}]})

	def test_find_related_reports_an_outage_when_both_searches_fail(self):
		frappe.set_user(self.owner)
		self.helpdesk.search_articles.side_effect = HelpdeskUnavailable("down")
		self.helpdesk.list_related_tickets.side_effect = HelpdeskUnavailable("down")

		with self.assertRaises(HelpdeskUnavailable):
			find_related(self.team, "broken mail")

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
