from __future__ import annotations

import html
import json

import frappe
import requests
from frappe import _
from frappe.utils import strip_html_tags

from central.iam import user_has_operator_bypass
from central.support import team_context_line

# Connect, read. A search answers while the customer types, so a late answer is useless.
SEARCH_TIMEOUT = (3, 5)
# Creating a ticket is worth a longer wait, because the customer waits for its number.
WRITE_TIMEOUT = (5, 30)
# What a Helpdesk that is down or in maintenance answers; Frappe's maintenance mode is a 503.
UNAVAILABLE = (502, 503, 504)
RELATED_TICKETS_LIMIT = 5
RELATED_SEARCH_LIMIT = 20
# Rows a related search may return. A Comment is an agent's internal note, and Central reads
# Helpdesk as an agent, so Helpdesk does not drop it for us.
CUSTOMER_VISIBLE_SEARCH_DOCTYPES = frozenset({"HD Ticket", "Communication"})
TEAM_TICKET_LIMIT = 500
SERVICE_USER_CACHE_SECONDS = 24 * 60 * 60

TICKET_FIELDS = [
	"name",
	"subject",
	"status",
	"status_category",
	"priority",
	"ticket_type",
	"raised_by",
	"creation",
	"modified",
]


class HelpdeskUnavailable(frappe.ValidationError):
	"""The Helpdesk site cannot be reached. A ticket can be tried again."""

	http_status_code = 503


class HelpdeskRequestFailed(frappe.ValidationError):
	"""Helpdesk refused a request or answered with something that is not Frappe's JSON."""


class HelpdeskClient:
	"""Calls a Frappe Helpdesk site's REST API as Central.
	Central creates and lists a team's tickets, and Helpdesk owns the tickets and the portal.
	A ticket's team is written into its description, which is how a list is narrowed to one team."""

	def __init__(self, base_url: str, api_key: str, api_secret: str):
		self.base_url = base_url.rstrip("/")
		self.api_key = api_key
		self.headers = {"Authorization": f"token {api_key}:{api_secret}"}

	@classmethod
	def from_settings(cls) -> HelpdeskClient:
		settings = frappe.get_cached_doc("Central Settings")
		api_secret = settings.get_password("helpdesk_api_secret", raise_exception=False)
		if not settings.helpdesk_url or not settings.helpdesk_api_key or not api_secret:
			frappe.throw(_("Support tickets are not configured in Central Settings."))

		return cls(settings.helpdesk_url, settings.helpdesk_api_key, api_secret)

	def ticket_portal_url(self, ticket_id: str | int) -> str:
		"""The ticket's page in the Helpdesk customer portal."""
		return f"{self.base_url}/help/my-tickets/{ticket_id}"

	def create_ticket(
		self,
		*,
		subject: str,
		description: str,
		raised_by: str,
		priority: str | None = None,
	) -> dict:
		"""Open a ticket in the customer portal on behalf of `raised_by`.
		→ its `name`, `subject`, `status`, `priority`, `creation` and portal `url`."""
		doc = {
			"doctype": "HD Ticket",
			"subject": subject,
			"description": description,
			"raised_by": raised_by,
			"via_customer_portal": 1,
			"utm_source": "central",
			"entry_point": "External",
		}
		if priority:
			doc["priority"] = priority

		ticket = self.call("frappe.client.insert", timeout=WRITE_TIMEOUT, doc=doc)

		return {
			"name": str(ticket["name"]),
			"subject": ticket.get("subject", subject),
			"status": ticket.get("status", "Open"),
			"priority": ticket.get("priority"),
			"creation": ticket.get("creation"),
			"url": self.ticket_portal_url(ticket["name"]),
		}

	def get_service_user(self) -> str:
		"""The Helpdesk user that Central's API key signs in as. It owns every ticket Central opens.
		Cached, because the key decides it and a list must not pay one more call each time."""
		key = f"central:helpdesk_service_user:{self.base_url}:{self.api_key}"
		user = frappe.cache.get_value(key)
		if not user:
			user = self.call("frappe.auth.get_logged_user")
			frappe.cache.set_value(key, user, expires_in_sec=SERVICE_USER_CACHE_SECONDS)

		return user

	def get_team_filters(self, team: str) -> list[list]:
		"""Tickets that Central opened for `team`. Anyone can email Helpdesk a description that
		copies the team line, so the ticket must also be owned by Central's service user."""
		return [
			["HD Ticket", "description", "like", f"%{team_context_line(team)}%"],
			["HD Ticket", "owner", "=", self.get_service_user()],
		]

	def list_open_tickets(self, team: str) -> list[dict]:
		"""The newest unresolved tickets that carry `team` in their context, each with its portal `url`.
		A ticket waiting on the customer is Paused, not Resolved, and is still open."""
		filters = [["HD Ticket", "status_category", "not in", ["Resolved"]], *self.get_team_filters(team)]
		rows = self.call(
			"frappe.client.get_list",
			doctype="HD Ticket",
			fields=TICKET_FIELDS,
			filters=filters,
			order_by="creation desc",
			limit_page_length=50,
		)

		return [row | {"url": self.ticket_portal_url(row["name"])} for row in rows or []]

	def article_portal_url(self, name: str, title_slug: str | None) -> str:
		"""The article's page in the Helpdesk portal, `<name>-<slug>` as the portal links it."""
		slug = f"{name}-{title_slug}" if title_slug else name
		return f"{self.base_url}/help/articles/{slug}"

	def search_articles(self, query: str) -> list[dict]:
		"""Helpdesk articles that match `query`, each with its portal `url`."""
		rows = self.get("helpdesk.api.knowledge_base.search_articles", query=query, limit=5)

		return [
			{
				"name": row["name"],
				"title": plain_text(row.get("title") or ""),
				"excerpt": plain_text(row.get("excerpt") or ""),
				"category": row.get("category_name"),
				"url": self.article_portal_url(row["name"], row.get("title_slug")),
			}
			for row in rows or []
		]

	def list_related_tickets(self, team: str, query: str) -> list[dict]:
		"""The team's tickets that match `query` in Helpdesk's full-text search, any status,
		each with its portal `url`. A closed ticket can still answer the question."""
		team_tickets = self.get_team_tickets(team)
		if not team_tickets:
			return []

		return self.pick_team_tickets(self.search_tickets(query, list(team_tickets)), team_tickets)

	def pick_team_tickets(self, rows: list[dict], team_tickets: dict[str, str | None]) -> list[dict]:
		"""The first matching rows that belong to the team, one row per ticket.
		`team_tickets` maps each team ticket to the email that raised it."""
		tickets = []
		seen = set()
		for row in rows:
			if row.get("doctype") not in CUSTOMER_VISIBLE_SEARCH_DOCTYPES:
				continue

			ticket = row.get("reference_ticket") or row.get("reference_name")
			subject = plain_text(row.get("title") or "")
			if ticket not in team_tickets or ticket in seen or not subject:
				continue

			seen.add(ticket)
			tickets.append(
				{
					"name": ticket,
					"subject": subject,
					"status": row.get("status"),
					"raised_by": team_tickets[ticket],
					"url": self.ticket_portal_url(ticket),
				}
			)
			if len(tickets) == RELATED_TICKETS_LIMIT:
				break

		return tickets

	def get_team_tickets(self, team: str) -> dict[str, str | None]:
		"""Every ticket Central opened for `team`, any status, mapped to the email that raised it."""
		rows = self.call(
			"frappe.client.get_list",
			doctype="HD Ticket",
			fields=["name", "raised_by"],
			filters=self.get_team_filters(team),
			limit_page_length=TEAM_TICKET_LIMIT,
		)

		return {row["name"]: row.get("raised_by") for row in rows or []}

	def search_tickets(self, query: str, names: list[str]) -> list[dict]:
		"""Helpdesk search rows for `query`, narrowed to the ticket names.
		The names go in a POST body, because a big team's list does not fit in a URL.
		A missing search index must not block the ticket form."""
		try:
			result = self.call(
				"helpdesk.api.search.search",
				query=query,
				filters=json.dumps({"reference_ticket": names}),
				limit=RELATED_SEARCH_LIMIT,
			)
		except frappe.ValidationError:
			return []

		return result.get("results") or []

	def call(self, method: str, timeout: tuple[int, int] = SEARCH_TIMEOUT, **body) -> dict | list:
		return self.read_request(requests.post, method, timeout, json=body)

	def get(self, method: str, **params) -> dict | list:
		return self.read_request(requests.get, method, SEARCH_TIMEOUT, params=params)

	def read_request(self, request, method: str, timeout: tuple[int, int], **kwargs) -> dict | list:
		try:
			response = request(
				f"{self.base_url}/api/method/{method}", headers=self.headers, timeout=timeout, **kwargs
			)
		except (requests.ConnectionError, requests.Timeout) as e:
			frappe.log_error(title="Helpdesk unreachable", message=f"{method}: {e}")
			raise HelpdeskUnavailable(
				_("Support is unavailable right now. Try again in a few minutes.")
			) from e

		return read(method, response)


def plain_text(markup: str) -> str:
	"""Markup from Helpdesk read as plain text, so `&amp;` reads as `&`."""
	return html.unescape(strip_html_tags(markup))


def read(method: str, response: requests.Response) -> dict | list:
	"""The `message` of a Helpdesk reply. Every failure is logged here, once, with its details.
	A customer reads a generic sentence, because Helpdesk's own errors are written for agents."""
	if response.status_code in UNAVAILABLE:
		frappe.log_error(title="Helpdesk unavailable", message=f"{method}: {response.status_code}")
		raise HelpdeskUnavailable(_("Support is unavailable right now. Try again in a few minutes."))

	body = None
	if response.status_code < 400:
		try:
			body = response.json()
		except ValueError:
			pass
	if not isinstance(body, dict):
		detail = f"{method}: {response.status_code}: {response.text[:2000]}"
		frappe.log_error(title="Helpdesk request failed", message=detail)
		if user_has_operator_bypass():
			frappe.throw(_("Helpdesk request failed ({0})").format(detail[:200]), HelpdeskRequestFailed)
		frappe.throw(_("Something went wrong with support. Try again later."), HelpdeskRequestFailed)

	return body.get("message", {})
