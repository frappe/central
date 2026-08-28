# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Project dashboard endpoints (ARCHITECTURE.md §2.1).

A team creates its own Projects and tags subscriptions into them to see a
per-project cost breakdown on its one consolidated invoice — Projects never
split the bill into separate invoices. Team-scoped via the capability IAM like
every dashboard endpoint: reads need `billing:view`, mutations `billing:manage`.
A project is always resolved back to its own team before a mutation touches it,
so a team can never rename/disable/re-limit another team's project by guessing
its name.

No delete endpoint: a project a team has already billed against is load-bearing
history (past Invoice Line Items carry its name/title as a snapshot) —
disabling is the customer-facing retirement path. `Subscription.validate_project`
already refuses new tags onto a disabled project, and its assets simply go
untagged (still billed, just without a project label) on future invoices.
"""

import frappe

from central.billing import authz
from central.billing.api.dashboard._shared import _require_manage, _resolve_team
from central.billing.catalog.subscriptions import anchor_subscription, project_run_rate


@frappe.whitelist()
def list_projects(team: str | None = None) -> list[dict]:
	"""The team's Projects, enriched with what the dashboard needs to show a
	project row: how many active resources it holds, the account standing of the
	subscription its resources anchor on, and its committed run-rate against its
	spending limit."""
	team = _resolve_team(team)
	projects = frappe.get_all(
		"Project",
		filters={"team": team},
		fields=["name", "title", "enabled", "spending_limit"],
		order_by="creation asc",
	)
	counts = _resource_counts(team)
	return [
		{
			**p,
			"resource_count": counts.get(p.name, 0),
			"standing": _project_standing(team, p.name),
			"committed_run_rate": project_run_rate(team, p.name),
		}
		for p in projects
	]


def _resource_counts(team: str) -> dict:
	"""Active (enabled) subscription count per Project, batched in one query."""
	rows = frappe.get_all(
		"Subscription",
		filters={"team": team, "enabled": 1, "project": ["is", "set"]},
		fields=["project"],
	)
	counts: dict[str, int] = {}
	for r in rows:
		counts[r.project] = counts.get(r.project, 0) + 1
	return counts


def _project_standing(team: str, project: str) -> str | None:
	"""The account standing of the team's anchor subscription — a project has no
	invoice of its own, so this is informational (the team's own standing)."""
	anchor = anchor_subscription(team)
	return frappe.db.get_value("Subscription", anchor, "account_standing") if anchor else None


@frappe.whitelist(methods=["POST"])
def create_project(title: str, team: str | None = None, spending_limit: float = 0) -> dict:
	"""Create a new Project for the team, enabled by default."""
	team = _resolve_team(team, authz.MANAGE)
	title = (title or "").strip()
	if not title:
		frappe.throw("Project needs a title.", frappe.ValidationError)
	doc = frappe.get_doc(
		{
			"doctype": "Project",
			"title": title,
			"team": team,
			"spending_limit": frappe.utils.flt(spending_limit),
		}
	).insert(ignore_permissions=True)
	return {"name": doc.name, "title": doc.title, "enabled": doc.enabled, "spending_limit": doc.spending_limit}


@frappe.whitelist(methods=["POST"])
def rename_project(name: str, title: str) -> dict:
	"""Rename a Project. Purely cosmetic — renaming never changes what it bills."""
	team = frappe.db.get_value("Project", name, "team")
	_require_manage(team)
	title = (title or "").strip()
	if not title:
		frappe.throw("Project needs a title.", frappe.ValidationError)
	doc = frappe.get_doc("Project", name)
	doc.title = title
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "title": doc.title}


@frappe.whitelist(methods=["POST"])
def set_project_enabled(name: str, enabled: bool | int) -> dict:
	"""Enable/disable a Project. Disabling stops new assets from being tagged into
	it (`Subscription.validate_project`); it does not untag existing ones, so
	re-enabling resumes tracking without retagging anything."""
	team = frappe.db.get_value("Project", name, "team")
	_require_manage(team)
	doc = frappe.get_doc("Project", name)
	doc.enabled = frappe.utils.cint(enabled)
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "enabled": doc.enabled}


@frappe.whitelist(methods=["POST"])
def set_project_spending_limit(name: str, spending_limit: float) -> dict:
	"""Set a Project's monthly committed-run-rate spending limit (0 = unlimited).

	Lowering it below what is already committed does not touch running assets —
	the limit only blocks tagging a *new* asset into the project going forward.
	"""
	team = frappe.db.get_value("Project", name, "team")
	_require_manage(team)
	doc = frappe.get_doc("Project", name)
	doc.spending_limit = frappe.utils.flt(spending_limit)
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "spending_limit": doc.spending_limit}
