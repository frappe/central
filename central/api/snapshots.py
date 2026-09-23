from __future__ import annotations

import math

import frappe
from frappe import _

from central.billing.api.dashboard._shared import _team_currency
from central.billing.catalog.snapshots import get_snapshot_rate
from central.billing.settings import daily_snapshot_retention_hours, free_snapshots_per_server
from central.infrastructure.doctype.vm_snapshot.vm_snapshot import VMSnapshot
from central.utils.guards import require_capability

SNAPSHOT_FIELDS = (
	"name",
	"title",
	"server",
	"region",
	"snapshot_type",
	"status",
	"size_mib",
	"creation",
	"expires_at",
	"is_free",
	"subscription",
	"is_restorable",
	"image_offering",
	"atlas_image_id",
	"error_detail",
)


@frappe.whitelist(methods=["GET"])
@require_capability("server:view", "You can't view this team's snapshots.")
def list_snapshots(team: str | None = None, resource_id: str | None = None) -> dict:
	"""The team's snapshots, newest first, each with what it costs. Pass `resource_id` for
	one server's snapshots and its automatic setting. Gated on `server:view`."""
	filters = {"team": team, "status": ["!=", "Deleted"]}
	if resource_id:
		filters["server"] = _team_server(team, resource_id).name

	rows = frappe.get_list(
		"VM Snapshot", filters=filters, fields=list(SNAPSHOT_FIELDS), order_by="creation desc", limit=0
	)
	servers = _server_titles(team, [row.server for row in rows])
	rates = _region_rates(team, {row.region for row in rows})
	snapshots = [_snapshot_row(row, servers, rates) for row in rows]

	result = {
		"snapshots": snapshots,
		"currency": _team_currency(team),
		"rates": rates,
		**_allowance(),
	}
	if resource_id:
		result["server"] = _automatic_setting(team, resource_id)
	return result


@frappe.whitelist(methods=["GET"])
@require_capability("server:view", "You can't view this team's snapshots.")
def snapshot_pricing(team: str | None = None, region: str | None = None) -> dict:
	"""The price per GB-month of a snapshot in `region`, shown before the customer commits."""
	rate, currency = get_snapshot_rate(team, region)
	return {"rate_per_gib": rate, "currency": currency, **_allowance()}


@frappe.whitelist(methods=["POST"])
@require_capability("server:snapshot", "You can't manage this team's snapshots.")
def take_snapshot(team: str | None = None, resource_id: str | None = None, title: str | None = None) -> dict:
	"""Take a paid snapshot of a server now. Gated on `server:snapshot`."""
	server = _team_server(team, resource_id)
	snapshot = frappe.get_doc(
		{
			"doctype": "VM Snapshot",
			"title": (title or "").strip() or _("{0} snapshot").format(server.title or server.name),
			"team": team,
			"server": server.name,
			"snapshot_type": "Manual",
		}
	)
	# The capability and team are checked above; the DocType grants no team write.
	snapshot.insert(ignore_permissions=True)
	return {"name": snapshot.name}


@frappe.whitelist(methods=["POST"])
@require_capability("server:snapshot", "You can't manage this team's snapshots.")
def keep_snapshot(team: str | None = None, name: str | None = None) -> dict:
	"""Keep a daily snapshot past its deletion time. Gated on `server:snapshot`."""
	_team_snapshot(team, name).keep()
	return {"name": name}


@frappe.whitelist(methods=["POST"])
@require_capability("server:snapshot", "You can't manage this team's snapshots.")
def delete_snapshots(team: str | None = None, names: list[str] | str | None = None) -> dict:
	"""Delete snapshots from their region. One failure does not stop the others; each
	reason comes back by name. Gated on `server:snapshot`."""
	if isinstance(names, str):
		names = frappe.parse_json(names)
	if not names:
		frappe.throw(_("Select at least one snapshot."))

	deleted, failed = [], {}
	for name in names:
		snapshot = _team_snapshot(team, name)
		try:
			snapshot.delete_from_region()
			deleted.append(name)
		except frappe.ValidationError as error:
			failed[name] = str(error)
	return {"deleted": deleted, "failed": failed}


@frappe.whitelist(methods=["POST"])
@require_capability("server:snapshot", "You can't manage this team's snapshots.")
def set_automatic_snapshots(
	team: str | None = None, resource_id: str | None = None, enabled: bool | int | str = True
) -> dict:
	"""Turn the daily free snapshot of one server on or off. Gated on `server:snapshot`."""
	server = _team_server(team, resource_id)
	server.db_set("skip_automatic_snapshot", 0 if frappe.utils.cint(enabled) else 1)
	return _automatic_setting(team, resource_id)


def _team_server(team: str, resource_id: str | None):
	name = frappe.db.get_value("Virtual Machine", {"team": team, "resource_id": resource_id}, "name")
	if not name:
		frappe.throw(_("No server '{0}' for this team.").format(resource_id), frappe.DoesNotExistError)
	return frappe.get_doc("Virtual Machine", name)


def _team_snapshot(team: str, name: str | None) -> VMSnapshot:
	if not name or frappe.db.get_value("VM Snapshot", name, "team") != team:
		frappe.throw(_("No snapshot '{0}' for this team.").format(name), frappe.DoesNotExistError)
	return frappe.get_doc("VM Snapshot", name)


def _automatic_setting(team: str, resource_id: str) -> dict:
	server = _team_server(team, resource_id)
	return {
		"resource_id": server.name,
		"automatic": not server.skip_automatic_snapshot,
		"region_automatic": bool(frappe.db.get_value("Region", server.cluster, "automatic_snapshots")),
	}


def _server_titles(team: str, servers: list[str]) -> dict[str, str]:
	names = list(set(servers))
	if not names:
		return {}
	rows = frappe.get_list(
		"Virtual Machine", filters={"team": team, "name": ["in", names]}, fields=["name", "title"], limit=0
	)
	return {row.name: row.title or row.name for row in rows}


def _region_rates(team: str, regions: set[str]) -> dict[str, float | None]:
	return {region: get_snapshot_rate(team, region)[0] for region in regions if region}


def _allowance() -> dict:
	return {
		"free_per_server": free_snapshots_per_server(),
		"daily_retention_hours": daily_snapshot_retention_hours(),
	}


def _snapshot_row(row, servers: dict[str, str], rates: dict[str, float | None]) -> dict:
	"""One snapshot as the console shows it: what it is, and what it costs a month when billed."""
	size_gib = math.ceil((row.size_mib or 0) / 1024)
	rate = rates.get(row.region)
	return {
		**{field: row[field] for field in SNAPSHOT_FIELDS if field != "subscription"},
		"server_title": servers.get(row.server, row.server),
		"size_gib": size_gib,
		"is_billed": bool(row.subscription),
		"monthly_cost": size_gib * rate if rate is not None else None,
	}
