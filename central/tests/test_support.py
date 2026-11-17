from __future__ import annotations

from unittest.mock import call, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.support import create_ticket, find_related, get_ticket_options, list_tickets
from central.iam import clear_grants_cache
from central.integrations.helpdesk import HelpdeskUnavailable
from central.support import backfill_helpdesk_customers, get_customer_contacts, team_context_line
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
		clear_grants_cache()

		self.helpdesk = self.enterContext(
			patch("central.api.support.HelpdeskClient")
		).from_settings.return_value
		self.helpdesk.create_ticket.return_value = {"name": "HD-1", "url": "https://support.test/help"}
		self.customer_helpdesk = self.enterContext(
			patch("central.support.HelpdeskClient")
		).from_settings.return_value
		self.own_ticket = {"name": "HD-9", "raised_by": self.owner, "url": "https://support.test/help/HD-9"}

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

	def _add_member(self, user: str, role: str, status: str = "Active") -> None:
		team = frappe.get_doc("Team", self.team)
		team.append("members", {"user": user, "role": role, "status": status})
		team.save()

	def _custom_role(self, capability: str) -> str:
		role = {"doctype": "Team Role", "role_name": f"{capability} {self.suffix}", "team": self.team}
		return frappe.get_doc(role | {"capabilities": [{"capability": capability}]}).insert().name

	def _grant_server(self, user: str, server: str) -> None:
		"""Make `user` a Developer on `server` only."""
		team = frappe.get_doc("Team", self.team)
		team.append(
			"members",
			{
				"user": user,
				"role": "Developer",
				"resource_type": "Server",
				"resource_name": server,
				"status": "Active",
			},
		)
		team.save()
		clear_grants_cache()

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

	def test_a_member_scoped_to_one_server_attaches_only_that_server_and_its_sites(self):
		scoped = ensure_user("support.scoped@example.test")
		second_server = ensure_server(f"support-second-{self.suffix}", self.team, title="web-3")
		second_site = self._site("second", self.team, second_server)
		self._grant_server(scoped, self.server)
		self._add_member(scoped, self._custom_role("support:view"))
		frappe.set_user(scoped)

		create_ticket(self.team, "server", SERVER_ISSUE, description="It broke.", server=self.server)
		create_ticket(self.team, "site", SITE_ISSUE, description="It broke.", site=self.site)
		with self.assertRaises(frappe.PermissionError):
			create_ticket(self.team, "server", SERVER_ISSUE, description="It broke.", server=second_server)
		with self.assertRaises(frappe.PermissionError):
			create_ticket(self.team, "site", SITE_ISSUE, description="It broke.", site=second_site)
		self.assertEqual(self.helpdesk.create_ticket.call_count, 2)

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
		self.assertEqual(kwargs["customer"], self.team)
		self.assertEqual(self.customer_helpdesk.sync_customer.call_args.args[0], self.team)
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

		self.helpdesk.list_open_tickets.assert_called_once_with(self.team, None)

	def test_a_viewer_lists_only_the_tickets_they_raised(self):
		viewer = ensure_user("support.viewer@example.test")
		self._add_member(viewer, "Viewer")
		frappe.set_user(viewer)

		list_tickets(self.team)
		find_related(self.team, "broken mail")

		self.helpdesk.list_open_tickets.assert_called_once_with(self.team, viewer)
		self.helpdesk.list_related_tickets.assert_called_once_with(self.team, "broken mail", viewer)

	def test_a_role_without_support_view_is_refused(self):
		member = ensure_user("support.norole@example.test")
		self._add_member(member, self._custom_role("server:view"))
		frappe.set_user(member)

		with self.assertRaises(frappe.PermissionError):
			list_tickets(self.team)
		self.helpdesk.list_open_tickets.assert_not_called()

	def test_a_teammates_ticket_does_not_link_to_the_portal(self):
		developer = ensure_user("support.developer@example.test")
		self._add_member(developer, "Developer")
		mate = {"name": "HD-8", "raised_by": self.owner, "url": "https://support.test/help/HD-8"}
		mine = self.own_ticket | {"raised_by": developer.upper()}
		self.helpdesk.list_open_tickets.return_value = [mine, mate]
		self.helpdesk.list_related_tickets.return_value = [mine, mate]

		frappe.set_user(developer)
		for tickets in (list_tickets(self.team), find_related(self.team, "broken mail")["tickets"]):
			self.assertEqual([ticket["url"] for ticket in tickets], [mine["url"], None])

		frappe.set_user("Administrator")
		self.assertEqual([ticket["url"] for ticket in list_tickets(self.team)], [mine["url"], mate["url"]])

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

	def _failed_sync(self, team: str, contacts: list[dict]) -> None:
		if team == self.team:
			raise RuntimeError("Helpdesk is down")

	def test_the_backfill_syncs_every_team_and_assigns_the_marked_tickets(self):
		self.enterContext(patch("central.support.is_helpdesk_configured", return_value=True))
		log_error = self.enterContext(patch("frappe.log_error"))
		self.customer_helpdesk.sync_customer.side_effect = self._failed_sync
		self.customer_helpdesk.list_marked_tickets.return_value = [
			{"name": "HD-1", "description": team_context_line(self.team)},
			{"name": "HD-2", "description": team_context_line(self.team)},
			{"name": "HD-3", "description": team_context_line(self.other_team)},
			{"name": "HD-4", "description": team_context_line("TEAM-404")},
		]

		backfill_helpdesk_customers()

		synced = [item.args[0] for item in self.customer_helpdesk.sync_customer.call_args_list]
		self.assertIn(self.team, synced)
		self.assertIn(self.other_team, synced)
		self.customer_helpdesk.set_ticket_customer.assert_has_calls(
			[call(["HD-1", "HD-2"], self.team), call(["HD-3"], self.other_team)]
		)
		self.assertEqual(self.customer_helpdesk.set_ticket_customer.call_count, 2)
		self.assertEqual(log_error.call_args.kwargs["title"], "Helpdesk customer backfill failed")

	def test_a_suspended_team_member_can_open_and_list_tickets(self):
		team = frappe.get_doc("Team", self.team)
		team.status = "Suspended"
		team.save()

		frappe.set_user(self.owner)
		create_ticket(self.team, "account", "Team suspension or archive", description="Why suspended?")
		list_tickets(self.team)

		self.helpdesk.create_ticket.assert_called_once()
		self.helpdesk.list_open_tickets.assert_called_once_with(self.team, self.owner)

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

	def test_a_critical_issue_is_urgent_and_any_other_takes_the_helpdesk_default(self):
		frappe.set_user(self.owner)

		create_ticket(self.team, "server", "Unreachable or down", description="Down.")
		self.assertEqual(self.helpdesk.create_ticket.call_args.kwargs["priority"], "Urgent")

		create_ticket(self.team, "server", SERVER_ISSUE, description="Slow.")
		self.assertIsNone(self.helpdesk.create_ticket.call_args.kwargs["priority"])

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
		self.helpdesk.list_related_tickets.return_value = [self.own_ticket]

		result = find_related(self.team, "  broken mail ")

		self.assertEqual(result, {"articles": [{"name": "kb-1"}], "tickets": [self.own_ticket]})
		self.helpdesk.search_articles.assert_called_once_with("broken mail")
		self.helpdesk.list_related_tickets.assert_called_once_with(self.team, "broken mail", None)

	def test_find_related_skips_articles_when_they_are_disabled(self):
		frappe.set_user(self.owner)
		frappe.db.set_single_value("Central Settings", "articles_enabled", 0)
		self.helpdesk.list_related_tickets.return_value = [self.own_ticket]

		result = find_related(self.team, "broken mail")

		self.helpdesk.search_articles.assert_not_called()
		self.assertEqual(result, {"articles": [], "tickets": [self.own_ticket]})

	def test_find_related_keeps_tickets_when_the_articles_fail(self):
		frappe.set_user(self.owner)
		self.helpdesk.search_articles.side_effect = HelpdeskUnavailable("down")
		self.helpdesk.list_related_tickets.return_value = [self.own_ticket]

		result = find_related(self.team, "broken mail")

		self.assertEqual(result, {"articles": [], "tickets": [self.own_ticket]})

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
