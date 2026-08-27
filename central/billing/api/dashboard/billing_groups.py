# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Billing Group dashboard endpoints (ARCHITECTURE.md §2.1).

A team creates its own Billing Groups and tags subscriptions, payment methods,
and credit top-ups into them to split its bill — one invoice per group, plus
the team's consolidated invoice for everything left ungrouped. Team-scoped via
the capability IAM like every dashboard endpoint: reads need `billing:view`,
mutations `billing:manage`. A group is always resolved back to its own team
before a mutation touches it, so a team can never rename/disable another
team's group by guessing its name.

No delete endpoint: a group a team has already billed against is load-bearing
history (`Invoice.billing_group` points at it) — disabling is the customer-facing
retirement path, and `Subscription.validate_billing_group` / `PaymentMethod`'s
own validation already refuse new tags onto a disabled group, while
generate.py folds its assets back into the consolidated invoice.
"""

import frappe

from central.billing import authz
from central.billing.api.dashboard._shared import _require_manage, _resolve_team
from central.billing.catalog.subscriptions import anchor_subscription


@frappe.whitelist()
def list_billing_groups(team: str | None = None) -> list[dict]:
	"""The team's Billing Groups, enriched with what the dashboard needs to show a
	group row: how many active resources it holds, and the account standing of the
	subscription its invoices anchor on (dunning/charge-routing track standing per
	scope, not per team — see `anchor_subscription`)."""
	team = _resolve_team(team)
	groups = frappe.get_all(
		"Billing Group",
		filters={"team": team},
		fields=["name", "title", "enabled"],
		order_by="creation asc",
	)
	counts = _resource_counts(team)
	return [
		{
			**g,
			"resource_count": counts.get(g.name, 0),
			"standing": _group_standing(team, g.name),
		}
		for g in groups
	]


def _resource_counts(team: str) -> dict:
	"""Active (enabled) subscription count per Billing Group, batched in one query."""
	rows = frappe.get_all(
		"Subscription",
		filters={"team": team, "enabled": 1, "billing_group": ["is", "set"]},
		fields=["billing_group"],
	)
	counts: dict[str, int] = {}
	for r in rows:
		counts[r.billing_group] = counts.get(r.billing_group, 0) + 1
	return counts


def _group_standing(team: str, billing_group: str) -> str | None:
	"""The account standing of the subscription this group's invoices anchor on —
	None only for a group no subscription has been tagged into yet."""
	anchor = anchor_subscription(team, billing_group)
	return frappe.db.get_value("Subscription", anchor, "account_standing") if anchor else None


@frappe.whitelist(methods=["POST"])
def create_billing_group(title: str, team: str | None = None) -> dict:
	"""Create a new Billing Group for the team, enabled by default."""
	team = _resolve_team(team, authz.MANAGE)
	title = (title or "").strip()
	if not title:
		frappe.throw("Billing Group needs a title.", frappe.ValidationError)
	doc = frappe.get_doc({"doctype": "Billing Group", "title": title, "team": team}).insert(
		ignore_permissions=True
	)
	return {"name": doc.name, "title": doc.title, "enabled": doc.enabled}


@frappe.whitelist(methods=["POST"])
def rename_billing_group(name: str, title: str) -> dict:
	"""Rename a Billing Group. Purely cosmetic — renaming never changes what it bills."""
	team = frappe.db.get_value("Billing Group", name, "team")
	_require_manage(team)
	title = (title or "").strip()
	if not title:
		frappe.throw("Billing Group needs a title.", frappe.ValidationError)
	doc = frappe.get_doc("Billing Group", name)
	doc.title = title
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "title": doc.title}


@frappe.whitelist(methods=["POST"])
def set_billing_group_enabled(name: str, enabled: bool | int) -> dict:
	"""Enable/disable a Billing Group. Disabling stops it partitioning the bill —
	its tagged subscriptions fold back onto the team's consolidated invoice from
	the next generation run (generate.py `_active_groups`); it does not untag them,
	so re-enabling resumes partitioning without retagging anything."""
	team = frappe.db.get_value("Billing Group", name, "team")
	_require_manage(team)
	doc = frappe.get_doc("Billing Group", name)
	doc.enabled = frappe.utils.cint(enabled)
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "enabled": doc.enabled}
