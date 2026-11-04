from __future__ import annotations

import json

import frappe
import requests
from frappe import _

from central.iam import user_has_operator_bypass
from central.support import team_context_line

# Connect, read: a console request must not hang on a Helpdesk that is down.
TIMEOUT = (30, 90)
# What a Helpdesk that is down or in maintenance answers; Frappe's maintenance mode is a 503.
UNAVAILABLE = (502, 503, 504)

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


class HelpdeskClient:
	"""Calls a Frappe Helpdesk site's REST API as Central.
	Central creates and lists a team's tickets, and Helpdesk owns the tickets and the portal.
	A ticket's team is written into its description, which is how a list is narrowed to one team."""

	def __init__(self, base_url: str, api_key: str, api_secret: str):
		self.base_url = base_url.rstrip("/")
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

		ticket = self.call("frappe.client.insert", doc=doc)

		return {
			"name": str(ticket["name"]),
			"subject": ticket.get("subject", subject),
			"status": ticket.get("status", "Open"),
			"priority": ticket.get("priority"),
			"creation": ticket.get("creation"),
			"url": self.ticket_portal_url(ticket["name"]),
		}

	def list_open_tickets(self, team: str) -> list[dict]:
		"""The newest unresolved tickets that carry `team` in their context, each with its portal `url`.
		A ticket waiting on the customer is Paused, not Resolved, and is still open."""
		filters = [
			["HD Ticket", "status_category", "not in", ["Resolved"]],
			["HD Ticket", "description", "like", f"%{team_context_line(team)}%"],
		]
		rows = self.call(
			"frappe.client.get_list",
			doctype="HD Ticket",
			fields=TICKET_FIELDS,
			filters=filters,
			order_by="creation desc",
			limit_page_length=50,
		)

		return [row | {"url": self.ticket_portal_url(row["name"])} for row in rows or []]

	def call(self, method: str, **body) -> dict | list:
		try:
			response = requests.post(
				f"{self.base_url}/api/method/{method}", json=body, headers=self.headers, timeout=TIMEOUT
			)
		except (requests.ConnectionError, requests.Timeout) as e:
			raise HelpdeskUnavailable(_("The support desk can't be reached right now.")) from e
		return read(response)


def read(response: requests.Response) -> dict | list:
	if response.status_code in UNAVAILABLE:
		raise HelpdeskUnavailable(_("The support desk is unavailable ({0}).").format(response.status_code))
	if response.status_code >= 400:
		message = refusal_message(response)
		if message:
			frappe.throw(message)
		detail = f"{response.status_code}: {response.text[:2000]}"
		frappe.log_error(title="Helpdesk request failed", message=detail)
		if user_has_operator_bypass():
			frappe.throw(_("Helpdesk request failed ({0})").format(detail[:200]))
		frappe.throw(_("The support desk could not complete the request. Try again later."))
	return response.json().get("message", {})


def refusal_message(response: requests.Response) -> str | None:
	"""Helpdesk's own sentence from a refusal, so a person reads why.
	It is the first of Frappe's `_server_messages`, else its `exception` line.
	None when the body is not Frappe's."""
	try:
		body = response.json()
		messages = [
			json.loads(raw).get("message") for raw in json.loads(body.get("_server_messages") or "[]")
		]
	except (ValueError, TypeError, AttributeError):
		return None
	return next((message for message in messages if message), None) or body.get("exception")
