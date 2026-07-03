from __future__ import annotations

import frappe
from frappe import _

from central.central.doctype.server_migration.server_migration import (
	ACTIVE_STATUSES,
	enqueue_migration,
)
from central.iam import can, resolve_team

# Server Migration endpoints for the console's Change Plan flow. A migration both
# provisions infrastructure in the target region and destroys the source VM, so it
# is gated on `server:create` AND `server:terminate` — strictly more than either
# alone. Reads follow the servers API convention: authorize the team, then curate
# fields (the doctype itself is locked to System Manager).

MIGRATION_PUBLIC_FIELDS = (
	"name",
	"asset",
	"from_cluster",
	"to_cluster",
	"pricing_mode",
	"plan",
	"status",
	"scheduled_at",
	"started_at",
)


@frappe.whitelist(methods=["POST"])
def migrate_server(
	team: str | None = None,
	resource_id: str | None = None,
	region: str | None = None,
	plan: str | None = None,
	includes: list | str | None = None,
	sub_category: str | None = None,
	scheduled_at: str | None = None,
) -> dict:
	"""Move a server to another region, optionally onto a different plan/config, now
	or at `scheduled_at`. Same-region plan changes belong to the resize endpoint —
	this one refuses them so there's exactly one path per operation."""
	user = frappe.session.user
	team = resolve_team(user, team)
	if not (can(user, team, "server:create") and can(user, team, "server:terminate")):
		frappe.throw(_("You can't migrate servers for this team."), frappe.PermissionError)

	asset = _source_asset(team, resource_id)
	if isinstance(includes, str):
		includes = frappe.parse_json(includes)
	_validate_choice(plan, includes, sub_category)

	doc = frappe.get_doc(
		{
			"doctype": "Server Migration",
			"asset": asset.name,
			"team": team,
			"from_cluster": asset.cluster,
			"to_cluster": region,
			"pricing_mode": "Preset" if plan else "Composed",
			"plan": plan,
			"sub_category": sub_category,
			"includes_json": frappe.as_json(includes) if includes else None,
			"scheduled_at": scheduled_at or None,
			"subscription": _active_subscription(team, asset.name),
		}
	).insert(ignore_permissions=True)

	_check_headroom(doc)
	if not doc.scheduled_at:
		enqueue_migration(doc.name)
	return {"migration": doc.name, "status": doc.status, "scheduled_at": doc.scheduled_at}


@frappe.whitelist(methods=["POST"])
def cancel_migration(team: str | None = None, migration: str | None = None) -> dict:
	"""Withdraw a scheduled migration. Gated on `server:create` (whoever can order a
	move can call it off); Running migrations refuse — the replacement may exist."""
	user = frappe.session.user
	team = resolve_team(user, team)
	if not can(user, team, "server:create"):
		frappe.throw(_("You can't cancel migrations for this team."), frappe.PermissionError)
	doc = frappe.get_doc("Server Migration", migration)
	if doc.team != team:
		frappe.throw(_("No migration '{0}' for this team.").format(migration), frappe.DoesNotExistError)
	doc.cancel_migration()
	return {"migration": doc.name, "status": doc.status}


@frappe.whitelist(methods=["GET"])
def list_migrations(team: str | None = None) -> list[dict]:
	"""The team's pending work: Scheduled + Running migrations, curated fields only.
	Gated on `server:view` (same scope as the registry the console pairs it with)."""
	user = frappe.session.user
	team = resolve_team(user, team)
	if not can(user, team, "server:view"):
		frappe.throw(_("You can't view this team's servers."), frappe.PermissionError)
	return frappe.get_all(
		"Server Migration",
		filters={"team": team, "status": ["in", ACTIVE_STATUSES]},
		fields=list(MIGRATION_PUBLIC_FIELDS),
		order_by="creation desc",
	)


def _source_asset(team: str, resource_id: str | None):
	if not resource_id:
		frappe.throw(_("resource_id is required."), frappe.ValidationError)
	asset = frappe.db.get_value(
		"Asset",
		{"resource_id": resource_id, "team": team},
		["name", "cluster", "status", "resize_in_progress", "migration_in_progress"],
		as_dict=True,
	)
	if not asset:
		frappe.throw(_("No server '{0}' for this team.").format(resource_id), frappe.DoesNotExistError)
	if asset.status == "Terminated":
		frappe.throw(_("This server is terminated."), frappe.ValidationError)
	if asset.resize_in_progress:
		frappe.throw(_("This server is resizing — migrate it once that finishes."))
	if asset.migration_in_progress:
		frappe.throw(_("This server is already migrating."))
	return asset


def _validate_choice(plan, includes, sub_category):
	"""Exactly one pricing mode, fully specified — mirrors create vs create_composed."""
	if plan and includes:
		frappe.throw(_("Pass a plan or a composed config, not both."), frappe.ValidationError)
	if not plan and not includes:
		frappe.throw(_("Pick a plan or a composed config for the destination."), frappe.ValidationError)
	if includes:
		from central.billing.catalog.composition import validate_composition

		validate_composition(sub_category, includes)


def _active_subscription(team: str, asset_name: str) -> str | None:
	return frappe.db.get_value("Subscription", {"team": team, "asset_id": asset_name, "enabled": 1}, "name")


def _check_headroom(doc) -> None:
	"""Refuse at request time what execution would refuse later, so the user hears
	"over budget" now, not from a failed background job. The job re-checks
	authoritatively (rates or caps may shift before a scheduled run)."""
	from central.billing.catalog.subscriptions import enforce_headroom
	from central.central.doctype.server_migration.server_migration import _target_rate

	enforce_headroom(doc.team, _target_rate(doc), exclude=doc.subscription)
