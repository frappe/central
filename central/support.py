from __future__ import annotations

import html

import frappe
from frappe import _

from central.iam import user_has_operator_bypass

SUPPORT_CATEGORIES: dict[str, tuple[str, ...]] = {
	"server": (
		"Unreachable or down",
		"Slow performance or high load",
		"Resize, disk, or plan",
		"SSH, console, or networking",
		"Snapshots or backups",
		"Other server issue",
	),
	"site": (
		"Site setup or provisioning failed",
		"Domain, DNS, or SSL certificate",
		"App installation or update",
		"Sign-in or administrator access",
		"Email delivery",
		"Other site issue",
	),
	"billing": (
		"Invoice or tax question",
		"Payment method or failed charge",
		"Credits or spending limit",
		"Plan or subscription",
		"Other billing question",
	),
	"account": (
		"Sign-in or verification",
		"Team members, roles, or invitations",
		"Object storage or LLM service",
		"Team suspension or archive",
		"Other account question",
	),
}

CATEGORY_LABELS = {
	"server": "Server",
	"site": "Site & app",
	"billing": "Billing & plans",
	"account": "Account & team",
}

CRITICAL_ISSUES = {
	"Unreachable or down",
	"Site setup or provisioning failed",
	"Payment method or failed charge",
}

MAXIMUM_SUBJECT_LENGTH = 140

SERVER_FIELDS = ("name", "resource_id", "atlas_vm_id", "title", "region", "status", "plan")
SITE_FIELDS = ("name", "subdomain", "server")


def team_context_line(team: str) -> str:
	"""The marker for a ticket's team, and the only text a list filters on.
	Central writes it after it escapes the customer's text, so a description cannot fake it."""
	return f"<hr><p><strong>Context</strong><br>Team: {html.escape(team)}<br>"


def is_articles_enabled() -> bool:
	"""Help articles stay hidden until an operator enables them, because a new deployment has none."""
	return bool(frappe.db.get_single_value("Central Settings", "articles_enabled"))


def get_ticket_options() -> list[dict]:
	"""The categories and issues the console offers, in catalog order."""
	return [
		{
			"key": key,
			"label": CATEGORY_LABELS[key],
			"issues": [{"label": issue, "is_critical": issue in CRITICAL_ISSUES} for issue in issues],
		}
		for key, issues in SUPPORT_CATEGORIES.items()
	]


def resolve_priority(issue_type: str) -> str | None:
	"""A critical issue reaches support first. Every other ticket takes Helpdesk's default."""
	return "Urgent" if issue_type in CRITICAL_ISSUES else None


def keep_own_ticket_links(tickets: list[dict]) -> list[dict]:
	"""Helpdesk's portal opens a ticket only for the person who raised it, so a teammate's ticket
	shows without a link. An operator keeps every link, because staff open tickets as agents."""
	if user_has_operator_bypass():
		return tickets

	email = (frappe.db.get_value("User", frappe.session.user, "email") or "").lower()

	return [
		ticket if (ticket.get("raised_by") or "").lower() == email else ticket | {"url": None}
		for ticket in tickets
	]


def get_user_email() -> str:
	"""The caller's email. A session user is usually an email, but an operator is `Administrator`.
	Helpdesk validates the ticket's `raised_by` as an email address."""
	email = frappe.db.get_value("User", frappe.session.user, "email")
	if not email:
		frappe.throw(_("Your account has no email address, so a ticket cannot be raised."))

	return email


def validate_ticket(category: str, issue_type: str, description: str) -> None:
	if category not in SUPPORT_CATEGORIES:
		frappe.throw(_("Choose what the ticket is about."))
	if issue_type not in SUPPORT_CATEGORIES[category]:
		frappe.throw(_("Choose the issue that fits your problem."))
	if not description.strip():
		frappe.throw(_("Describe the problem so the team can help."))


def get_server(team: str, server: str) -> dict:
	"""The named server, only when this team owns it and the caller may view it.
	The ticket shows the server's details back to the caller, so a scoped grant must cover it."""
	rows = frappe.get_list(
		"Virtual Machine", filters={"resource_id": server, "team": team}, fields=list(SERVER_FIELDS), limit=1
	)
	if not rows:
		frappe.throw(_("You can't attach that server to a ticket."), frappe.PermissionError)

	return rows[0]


def get_site(team: str, site: str) -> dict:
	"""The named site, only when this team owns it and the caller may view it."""
	rows = frappe.get_list("Site", filters={"name": site, "team": team}, fields=list(SITE_FIELDS), limit=1)
	if not rows:
		frappe.throw(_("You can't attach that site to a ticket."), frappe.PermissionError)

	return rows[0]


def build_subject(category: str, issue_type: str, subject: str) -> str:
	"""The ticket list shows one line, so the category and topic lead it.
	The customer's words keep whatever room the label leaves."""
	label = f"[{CATEGORY_LABELS[category]} · {issue_type}]"
	text = subject.strip() or issue_type
	room = MAXIMUM_SUBJECT_LENGTH - len(label) - 1

	return f"{label} {text[:room]}" if room > 0 else label[:MAXIMUM_SUBJECT_LENGTH]


def build_description(
	description: str,
	team: str,
	category: str,
	issue_type: str,
	server: dict | None,
	site: dict | None,
) -> str:
	"""The customer's words, then a block that says who raised the ticket and what it is about.
	A team reads its open tickets by the exact team line in this block.
	The customer's text is escaped, so it cannot fake that line."""
	details = [
		("User", frappe.session.user),
		("Category", CATEGORY_LABELS[category]),
		("Topic", issue_type),
	]
	details.extend(describe_server(server))
	details.extend(describe_site(site))
	context = "".join(f"{html.escape(label)}: {html.escape(value)}<br>" for label, value in details)

	return (
		f"{format_text(description)}{team_context_line(team)}{context}{central_links(team, server, site)}</p>"
	)


def central_links(team: str, server: dict | None, site: dict | None) -> str:
	"""Links to the records the ticket is about, so an agent opens them from the ticket."""
	base = frappe.utils.get_url()
	links = [f'<a href="{base}/app/team/{html.escape(team, quote=True)}">Team</a>']
	if server:
		name = html.escape(server["name"], quote=True)
		links.append(f'<a href="{base}/app/virtual-machine/{name}">Server</a>')
	if site:
		links.append(f'<a href="{base}/app/site/{html.escape(site["name"], quote=True)}">Site</a>')

	return f"Open in Central: {' · '.join(links)}<br>"


def describe_server(server: dict | None) -> list[tuple[str, str]]:
	if not server:
		return []
	parts = (
		server["title"],
		server["resource_id"],
		server["region"],
		server["plan"],
		server["status"],
	)

	return [("Server", " · ".join(part for part in parts if part))]


def describe_site(site: dict | None) -> list[tuple[str, str]]:
	if not site:
		return []
	address = f"{site['subdomain']} ({site['name']})" if site["subdomain"] else site["name"]

	return [("Site", f"{address} on {site['server']}" if site["server"] else address)]


def format_text(text: str) -> str:
	"""The customer's text goes into HTML, so escape it and keep its line breaks."""
	return html.escape(text.strip()).replace("\n", "<br>")
