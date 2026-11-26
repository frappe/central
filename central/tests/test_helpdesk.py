from __future__ import annotations

import json
from unittest.mock import patch

import frappe
import requests
from frappe.tests import IntegrationTestCase

from central.integrations.helpdesk import (
	CONTACT_INSERT_LIMIT,
	SEARCH_TIMEOUT,
	TEAM_TICKET_LIMIT,
	TICKET_FIELDS,
	WRITE_TIMEOUT,
	HelpdeskClient,
	HelpdeskRequestFailed,
	HelpdeskUnavailable,
)
from central.tests.test_iam import ensure_user


class TestHelpdeskClient(IntegrationTestCase):
	def setUp(self):
		self.client = HelpdeskClient("https://support.test/", "key", "secret")
		self.enterContext(
			patch.object(HelpdeskClient, "get_service_user", return_value="central@support.test")
		)

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
				subject="Slow",
				description="It lags.",
				raised_by="owner@example.test",
				customer="TEAM-1",
				priority="High",
			)

		self.assertEqual(ticket["url"], "https://support.test/help/my-tickets/HD-1")
		self.assertEqual(post.call_args.args[0], "https://support.test/api/method/frappe.client.insert")
		doc = post.call_args.kwargs["json"]["doc"]
		self.assertEqual(doc["doctype"], "HD Ticket")
		self.assertEqual(doc["customer"], "TEAM-1")
		self.assertEqual(doc["via_customer_portal"], 1)
		self.assertEqual(doc["utm_source"], "central")
		self.assertEqual(doc["priority"], "High")
		self.assertEqual(post.call_args.kwargs["timeout"], WRITE_TIMEOUT)

	def test_open_tickets_are_narrowed_to_the_customer(self):
		body = {"message": [{"name": "HD-1", "subject": "Slow"}]}
		with patch(
			"central.integrations.helpdesk.requests.post", return_value=self.response(200, body)
		) as post:
			tickets = self.client.list_open_tickets(team="TEAM-1")

		self.assertEqual(tickets[0]["url"], "https://support.test/help/my-tickets/HD-1")
		request = post.call_args.kwargs["json"]
		self.assertEqual(
			request["filters"],
			[
				["HD Ticket", "customer", "=", "TEAM-1"],
				["HD Ticket", "status_category", "not in", ["Resolved"]],
			],
		)
		self.assertEqual(request["fields"], TICKET_FIELDS)
		self.assertEqual(request["order_by"], "creation desc")
		self.assertEqual(request["limit_page_length"], 50)

	def test_sync_customer_creates_the_customer_only_when_it_is_missing(self):
		contacts = [{"email": "owner@example.test", "full_name": "Owner", "is_manager": True}]
		with patch(
			"central.integrations.helpdesk.requests.post",
			side_effect=[
				self.response(200, {"message": []}),
				self.response(200, {"message": {"name": "TEAM-1"}}),
				self.response(200, {"message": [{"name": "CT-1", "email_id": "owner@example.test"}]}),
				self.response(200, {"message": {"name": "TEAM-1"}}),
			],
		) as post:
			self.client.sync_customer("TEAM-1", contacts)

		methods = [call.args[0].rsplit("/", 1)[-1] for call in post.call_args_list]
		self.assertEqual(
			methods,
			[
				"frappe.client.get_list",
				"frappe.client.insert",
				"frappe.client.get_list",
				"frappe.client.set_value",
			],
		)
		self.assertEqual(
			post.call_args_list[1].kwargs["json"]["doc"],
			{"doctype": "HD Customer", "customer_name": "TEAM-1"},
		)
		self.assertEqual(
			post.call_args_list[3].kwargs["json"]["fieldname"],
			{"contacts": [{"contact_name": "CT-1", "is_manager": 1}]},
		)

	def test_sync_customer_adds_only_the_missing_contacts_in_one_call(self):
		contacts = [
			{"email": "Owner@Example.test", "full_name": "Owner", "is_manager": True},
			{"email": "dev@example.test", "full_name": "", "is_manager": False},
		]
		with patch(
			"central.integrations.helpdesk.requests.post",
			side_effect=[
				self.response(200, {"message": [{"name": "TEAM-1"}]}),
				self.response(200, {"message": [{"name": "CT-1", "email_id": "owner@example.test"}]}),
				self.response(200, {"message": ["CT-2"]}),
				self.response(200, {"message": {"name": "TEAM-1"}}),
			],
		) as post:
			self.client.sync_customer("TEAM-1", contacts)

		insert_many = post.call_args_list[2].kwargs["json"]
		self.assertEqual(
			insert_many["docs"],
			[
				{
					"doctype": "Contact",
					"first_name": "dev@example.test",
					"email_ids": [{"email_id": "dev@example.test", "is_primary": 1}],
				}
			],
		)
		self.assertEqual(post.call_args_list[2].kwargs["timeout"], WRITE_TIMEOUT)
		self.assertEqual(
			post.call_args_list[3].kwargs["json"]["fieldname"],
			{
				"contacts": [
					{"contact_name": "CT-1", "is_manager": 1},
					{"contact_name": "CT-2", "is_manager": 0},
				]
			},
		)

	def test_sync_customer_inserts_contacts_in_batches_the_helpdesk_accepts(self):
		contacts = [
			{"email": f"member{index}@example.test", "full_name": "", "is_manager": False}
			for index in range(CONTACT_INSERT_LIMIT + 1)
		]
		with patch(
			"central.integrations.helpdesk.requests.post",
			side_effect=[
				self.response(200, {"message": [{"name": "TEAM-1"}]}),
				self.response(200, {"message": []}),
				self.response(200, {"message": [f"CT-{index}" for index in range(CONTACT_INSERT_LIMIT)]}),
				self.response(200, {"message": ["CT-LAST"]}),
				self.response(200, {"message": {"name": "TEAM-1"}}),
			],
		) as post:
			self.client.sync_customer("TEAM-1", contacts)

		batches = [call.kwargs["json"]["docs"] for call in post.call_args_list[2:4]]
		self.assertEqual([len(batch) for batch in batches], [CONTACT_INSERT_LIMIT, 1])
		self.assertEqual(
			len(post.call_args_list[4].kwargs["json"]["fieldname"]["contacts"]),
			CONTACT_INSERT_LIMIT + 1,
		)

	def test_sync_customer_clears_the_contacts_of_a_team_without_members(self):
		with patch(
			"central.integrations.helpdesk.requests.post",
			side_effect=[
				self.response(200, {"message": [{"name": "TEAM-1"}]}),
				self.response(200, {"message": {"name": "TEAM-1"}}),
			],
		) as post:
			self.client.sync_customer("TEAM-1", [])

		self.assertEqual(post.call_count, 2)
		self.assertEqual(post.call_args_list[1].kwargs["json"]["fieldname"], {"contacts": []})

	def test_an_unavailable_status_says_the_helpdesk_is_unavailable(self):
		for status in (502, 503, 504):
			with self.subTest(status=status):
				with patch(
					"central.integrations.helpdesk.requests.post",
					return_value=self.response(status, {}),
				):
					with self.assertRaises(HelpdeskUnavailable) as caught:
						self.client.list_open_tickets(team="TEAM-1")
				self.assertEqual(caught.exception.http_status_code, 503)

	def test_a_connection_timeout_says_the_helpdesk_is_unavailable(self):
		with patch("central.integrations.helpdesk.requests.post", side_effect=requests.Timeout):
			with self.assertRaises(HelpdeskUnavailable):
				self.client.create_ticket(
					subject="Slow", description="It lags.", raised_by="a@b.test", customer="TEAM-1"
				)

	def test_search_articles_strips_html_and_builds_the_portal_url(self):
		body = {
			"message": [
				{
					"name": "kb-1",
					"title": "<b>Mail</b> &amp; DNS setup",
					"excerpt": "Set <mark>up</mark> mail",
					"title_slug": "mail-dns-setup",
					"category_name": "Frappe Cloud",
				}
			]
		}
		with patch(
			"central.integrations.helpdesk.requests.get", return_value=self.response(200, body)
		) as get:
			articles = self.client.search_articles("mail")

		self.assertEqual(
			articles,
			[
				{
					"name": "kb-1",
					"title": "Mail & DNS setup",
					"excerpt": "Set up mail",
					"category": "Frappe Cloud",
					"url": "https://support.test/help/articles/kb-1-mail-dns-setup",
				}
			],
		)
		self.assertEqual(
			get.call_args.args[0],
			"https://support.test/api/method/helpdesk.api.knowledge_base.search_articles",
		)
		self.assertEqual(get.call_args.kwargs["params"], {"query": "mail", "limit": 5})

	def test_related_tickets_use_the_team_list_and_full_text_search(self):
		names = {"message": [{"name": "HD-9", "raised_by": "owner@example.test"}]}
		found = {
			"message": {
				"results": [
					{
						"doctype": "HD Ticket",
						"reference_ticket": "HD-1",
						"title": "Someone else",
						"status": "Open",
					},
					{
						"doctype": "HD Ticket",
						"reference_ticket": "HD-9",
						"title": "Mail &amp; DNS broken",
						"status": "Resolved",
					},
				]
			}
		}
		with patch(
			"central.integrations.helpdesk.requests.post",
			side_effect=[
				self.response(200, names),
				self.response(200, found),
			],
		) as post:
			tickets = self.client.list_related_tickets(team="TEAM-1", query="mail broken")

		self.assertEqual(
			tickets,
			[
				{
					"name": "HD-9",
					"subject": "Mail & DNS broken",
					"status": "Resolved",
					"raised_by": "owner@example.test",
					"url": "https://support.test/help/my-tickets/HD-9",
				}
			],
		)
		names_call, search_call = post.call_args_list
		self.assertEqual(names_call.kwargs["json"]["filters"], [["HD Ticket", "customer", "=", "TEAM-1"]])
		self.assertEqual(names_call.kwargs["json"]["fields"], ["name", "raised_by"])
		self.assertEqual(names_call.kwargs["json"]["limit_page_length"], TEAM_TICKET_LIMIT)

		self.assertEqual(search_call.args[0], "https://support.test/api/method/helpdesk.api.search.search")
		search = search_call.kwargs["json"]
		self.assertEqual(search["query"], "mail broken")
		self.assertEqual(json.loads(search["filters"]), {"reference_ticket": ["HD-9"]})
		self.assertEqual(search["limit"], 20)
		self.assertEqual(search_call.kwargs["timeout"], SEARCH_TIMEOUT)

	def test_related_tickets_without_a_team_ticket_skip_search(self):
		with patch(
			"central.integrations.helpdesk.requests.post",
			side_effect=[self.response(200, {"message": []})],
		) as post:
			self.assertEqual(self.client.list_related_tickets(team="TEAM-1", query="mail broken"), [])

		self.assertEqual(post.call_count, 1)

	def test_a_communication_hit_maps_to_its_ticket(self):
		names = {"message": [{"name": "HD-9", "raised_by": "owner@example.test"}]}
		found = {
			"message": {
				"results": [
					{
						"doctype": "Communication",
						"reference_name": "HD-9",
						"title": "Re: Mail &amp; DNS",
						"status": None,
					}
				]
			}
		}
		with patch(
			"central.integrations.helpdesk.requests.post",
			side_effect=[
				self.response(200, names),
				self.response(200, found),
			],
		):
			tickets = self.client.list_related_tickets(team="TEAM-1", query="mail broken")

		self.assertEqual(
			tickets,
			[
				{
					"name": "HD-9",
					"subject": "Re: Mail & DNS",
					"status": None,
					"raised_by": "owner@example.test",
					"url": "https://support.test/help/my-tickets/HD-9",
				}
			],
		)

	def test_an_agent_comment_never_becomes_a_related_ticket(self):
		names = {"message": [{"name": "HD-9", "raised_by": "owner@example.test"}]}
		found = {
			"message": {
				"results": [
					{"doctype": "Comment", "reference_ticket": "HD-9", "title": "Internal: refund approved"}
				]
			}
		}
		with patch(
			"central.integrations.helpdesk.requests.post",
			side_effect=[
				self.response(200, names),
				self.response(200, found),
			],
		):
			self.assertEqual(self.client.list_related_tickets(team="TEAM-1", query="refund"), [])

	def test_a_refusal_shows_a_generic_message_and_logs_the_detail(self):
		frappe.set_user(ensure_user("support.reader@example.test"))
		self.addCleanup(frappe.set_user, "Administrator")
		body = {"exception": "frappe.exceptions.PermissionError: Agent api@support.test lacks HD Team"}
		with (
			patch("central.integrations.helpdesk.requests.post", return_value=self.response(403, body)),
			patch("central.integrations.helpdesk.frappe.log_error") as log_error,
		):
			with self.assertRaises(HelpdeskRequestFailed) as caught:
				self.client.list_open_tickets(team="Support")

		self.assertNotIn("api@support.test", str(caught.exception))
		self.assertIn("api@support.test", log_error.call_args.kwargs["message"])

	def test_a_reply_that_is_not_json_fails_cleanly(self):
		response = requests.Response()
		response.status_code = 200
		response._content = b"<html>Maintenance</html>"
		with patch("central.integrations.helpdesk.requests.post", return_value=response):
			with self.assertRaises(HelpdeskRequestFailed):
				self.client.list_open_tickets(team="Support")


class TestHelpdeskServiceUser(IntegrationTestCase):
	def test_the_service_user_is_asked_once_and_cached(self):
		client = HelpdeskClient("https://support.test", "key-cache", "secret")
		frappe.cache.delete_value(f"central:helpdesk_service_user:{client.base_url}:{client.api_key}")
		reply = requests.Response()
		reply.status_code = 200
		reply._content = json.dumps({"message": "central@support.test"}).encode()

		with patch("central.integrations.helpdesk.requests.post", return_value=reply) as post:
			self.assertEqual(client.get_service_user(), "central@support.test")
			self.assertEqual(client.get_service_user(), "central@support.test")

		post.assert_called_once()
		self.assertEqual(
			post.call_args.args[0], "https://support.test/api/method/frappe.auth.get_logged_user"
		)
