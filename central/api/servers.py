from __future__ import annotations

import frappe
from frappe import _

from central.central.doctype.resource_action.resource_action import ResourceAction
from central.errors import resource_action
from central.iam import can, resolve_team
from central.integrations.servers import reconcile

# Server endpoints for the console. Reads come from the Asset mirror; commands go
# to Atlas as the operator (Atlas stays policy-unaware — capability gating happens
# here). Every call resolves and authorizes a team first.

# `list_instances` merges an Active Atlas Instance's liveness with its Region's
# display metadata. Only these non-secret Atlas Instance fields are ever read —
# the credentials/tunnel internals (api_key/api_secret/base_url/tunnel_*/peer_*/
# service_user) now sit apart from the map metadata, which lives on Region.
INSTANCE_LIVENESS_FIELDS = ("region", "status", "reachable")
REGION_DISPLAY_FIELDS = ("display_name", "provider", "country_code", "latitude", "longitude")


@frappe.whitelist(methods=["GET"])
def registry(team: str | None = None) -> dict:
	"""List a team's VMs — servers (the Asset mirror) and self-serve sites (the Site
	mirror, each a 1:1-backed VM) — in one read, so the console's map/panel unify them
	from a single call. A pure read; gated on `server:view`. Terminated sites are gone,
	not a state to render, so they're excluded here (Terminated assets are filtered by
	the map feed client-side)."""
	user = frappe.session.user
	team = resolve_team(user, team)
	if not can(user, team, "server:view"):
		frappe.throw(_("You can't view this team's servers."), frappe.PermissionError)

	assets = frappe.get_list(
		"Asset",
		filters={"team": team},
		fields=[
			"name",
			"resource_id",
			"title",
			"cluster",
			"status",
			"plan",
			"frappe_version",
			"vcpus",
			"memory_megabytes",
			"disk_gigabytes",
			"ipv6_address",
			"public_ipv4",
			"gateway_url",
			"resize_in_progress",
			"state_observed_at",
		],
		order_by="cluster asc, resource_id asc",
		limit_page_length=0,
	)
	# Overlay the transitional label of any in-flight action, so a just-clicked
	# start/stop/terminate (or a still-provisioning create) reads as "…ing" until the
	# mirror catches up — instead of looking like nothing happened.
	pending = ResourceAction.pending_labels(team)
	for asset in assets:
		asset["pending_action"] = pending.get(asset["resource_id"])

	# A creation has no server row until the region accepts it, so it cannot be overlaid
	# like the pending actions above. It rides here as its own list: the console picks its
	# own request back up after a reload, and the fleet can show what is still building.
	creations = ResourceAction.open_creations(team)

	# A site is a VM too — flat and uncapped, symmetric with servers. `name` is the FQDN
	# (the stable id + terminate key); `subdomain` is the user-entered display name.
	sites = frappe.get_list(
		"Site",
		filters={"team": team, "status": ["!=", "Terminated"]},
		fields=["name", "subdomain", "status", "url", "region"],
		order_by="subdomain asc",
		limit_page_length=0,
	)
	# Same overlay for sites; a VM id and a site FQDN never collide, so one map covers both.
	for site in sites:
		site["pending_action"] = pending.get(site["name"])

	return {"team": team, "assets": assets, "sites": sites, "creations": creations}


@frappe.whitelist(methods=["GET"])
def server_overview(team: str | None = None, resource_id: str | None = None) -> dict:
	"""Return one server's Central mirror plus Pilot's cached operational metrics."""
	user = frappe.session.user
	team = resolve_team(user, team)
	if not can(user, team, "server:view"):
		frappe.throw(_("You can't view this team's servers."), frappe.PermissionError)
	if not resource_id:
		frappe.throw(_("resource_id is required."), frappe.ValidationError)

	row = _overview_asset_row(resource_id, team)
	if not row:
		frappe.throw(_("No server '{0}' for this team.").format(resource_id), frappe.DoesNotExistError)

	asset = frappe._dict(
		{
			"resource_id": row.resource_id,
			"title": row.title,
			"cluster": row.cluster,
			"status": row.status,
			"plan": row.plan,
			"frappe_version": row.frappe_version,
			"vcpus": row.vcpus,
			"memory_megabytes": row.memory_megabytes,
			"disk_gigabytes": row.disk_gigabytes,
			"ipv6_address": row.ipv6_address,
			"public_ipv4": row.public_ipv4,
			"gateway_url": row.gateway_url,
			"creation": row.creation,
		}
	)
	return {
		"server": {
			**asset,
			**_overview_plan(asset, team),
			"team_name": row.team_name or team,
			"region": {
				"display_name": row.region_display_name or asset.cluster,
				"provider": row.region_provider,
				"country_code": row.region_country_code,
			},
		},
		"monitoring": _server_monitoring(asset, audience_id=row.audience_id),
	}


def _overview_asset_row(resource_id: str, team: str):
	"""Asset + region + team + active Pilot audience in one query."""
	asset = frappe.qb.DocType("Asset")
	region = frappe.qb.DocType("Region")
	team_table = frappe.qb.DocType("Team")
	pilot = frappe.qb.DocType("Pilot Credential")
	rows = (
		frappe.qb.from_(asset)
		# Asset.cluster links to Atlas Instance, and an Atlas Instance is autonamed
		# after its region (autoname: field:region), so its name IS the Region name —
		# hence Region.name == Asset.cluster. This invariant (one Atlas per region,
		# named for it) is what lets us skip the Asset→Atlas Instance→Region hop.
		.left_join(region)
		.on(region.name == asset.cluster)
		.left_join(team_table)
		.on(team_table.name == asset.team)
		.left_join(pilot)
		.on((pilot.asset == asset.name) & (pilot.status == "Active"))
		.select(
			asset.resource_id,
			asset.title,
			asset.cluster,
			asset.status,
			asset.plan,
			asset.frappe_version,
			asset.vcpus,
			asset.memory_megabytes,
			asset.disk_gigabytes,
			asset.ipv6_address,
			asset.public_ipv4,
			asset.gateway_url,
			asset.creation,
			region.display_name.as_("region_display_name"),
			region.provider.as_("region_provider"),
			region.country_code.as_("region_country_code"),
			team_table.team_name.as_("team_name"),
			pilot.audience_id.as_("audience_id"),
		)
		.where((asset.resource_id == resource_id) & (asset.team == team))
		.limit(1)
		.run(as_dict=True)
	)
	return rows[0] if rows else None


def _overview_plan(asset: dict, team: str) -> dict:
	"""Tier name + billed rate — scoped to this asset, not the team's full run-rate.

	Reads the asset's open priced segment through the billing seam
	(`active_segment_for_resource`) rather than querying Subscription / Subscription
	Change and re-deriving the ledger's open-segment rule here — servers does not own
	how a segment resolves from the billing ledger."""
	from central.billing.catalog.subscriptions import active_segment_for_resource

	currency = frappe.db.get_value("Billing Profile", team, "currency") or "INR"
	billing_cycle = "Monthly"
	title = None
	rate = None
	plan_name = asset.plan

	segment = active_segment_for_resource(asset.resource_id)
	if segment:
		plan_name = segment.plan or plan_name
		# Only adopt the segment's currency/rate once a plan is attached: an Asset can
		# open a Subscription during bootstrap before a plan exists, and that segment
		# has no meaningful price to show (keep the profile-default currency then).
		if plan_name:
			currency = segment.currency or currency
			# A priced open segment carries a locked_rate; an unpriced one (0/None)
			# falls through to the catalog rate below.
			if segment.locked_rate:
				rate = frappe.utils.flt(segment.locked_rate)

	if plan_name:
		plan = frappe.db.get_value("Plan", plan_name, ["title", "billing_cycle"], as_dict=True)
		if plan:
			title = plan.title
			billing_cycle = plan.billing_cycle or "Monthly"
			if rate is None:
				# Local import: Plan.get_rate pulls billing catalog; keep servers import-light.
				rate = frappe.get_cached_doc("Plan", plan_name).get_rate(currency, asset.cluster)
	else:
		# Asset bootstrap may open a Subscription before a plan is attached — no rate to show.
		rate = None

	return {
		"plan_title": title,
		"plan_rate": rate,
		"plan_currency": currency,
		"plan_billing_cycle": billing_cycle,
	}


def _server_monitoring(asset: dict, audience_id: str | None = None) -> dict:
	"""Pilot metrics are meaningful only for a live, enrolled bench VM."""
	if asset.status != "Running" or not asset.gateway_url or not audience_id:
		return {"available": False}

	from central.integrations.pilot import get_cached_monitoring

	return get_cached_monitoring(asset.resource_id, asset.gateway_url, audience_id)


@frappe.whitelist(methods=["GET"])
def list_instances(team: str | None = None) -> list[dict]:
	"""List the regions a team can place servers in — every Active Atlas Instance.
	A pure read for the console's New Server region picker. Gated on `cluster:view`
	(same scope as `registry`); the team only resolves the gate, the region set is
	team-agnostic."""
	user = frappe.session.user
	team = resolve_team(user, team)
	if not can(user, team, "cluster:view"):
		frappe.throw(_("You can't view clusters for this team."), frappe.PermissionError)
	# Atlas Instance is global infrastructure holding per-instance API credentials,
	# so the DocType is locked to System Manager. `cluster:view` already authorizes
	# this read, so we bypass DocType RBAC and read only the non-secret liveness
	# fields — otherwise a Central User (e.g. a team Owner) gets an empty list.
	instances = frappe.get_all(
		"Atlas Instance",
		filters={"status": "Active"},
		fields=list(INSTANCE_LIVENESS_FIELDS),
		order_by="region asc",
	)
	# Merge each region's display metadata (kept on Region, away from the secrets).
	display = {
		row.name: row
		for row in frappe.get_all(
			"Region",
			filters={"name": ["in", [i.region for i in instances]]},
			fields=["name", *REGION_DISPLAY_FIELDS],
		)
	}
	for instance in instances:
		meta = display.get(instance.region)
		for field in REGION_DISPLAY_FIELDS:
			instance[field] = meta.get(field) if meta else None
	return instances


@frappe.whitelist(methods=["POST"])
def refresh_assets(team: str | None = None) -> dict:
	"""Manually reconcile this team's mirror from every Active Atlas — the on-demand
	twin of the scheduled reconcile. Gated on `server:view`."""
	user = frappe.session.user
	team = resolve_team(user, team)

	if not can(user, team, "server:view"):
		frappe.throw(_("You can't refresh this team's servers."), frappe.PermissionError)
	return reconcile(team)


@frappe.whitelist(methods=["POST"])
@resource_action
def start_server(team: str | None = None, resource_id: str | None = None) -> dict:
	"""Start a stopped server. Gated on `server:power`."""
	return _run_command("start", team, resource_id)


@frappe.whitelist(methods=["POST"])
@resource_action
def stop_server(team: str | None = None, resource_id: str | None = None) -> dict:
	"""Stop a running server. Gated on `server:power`."""
	return _run_command("stop", team, resource_id)


@frappe.whitelist(methods=["POST"])
@resource_action
def restart_server(team: str | None = None, resource_id: str | None = None) -> dict:
	"""Restart a running server. Gated on `server:power`."""
	return _run_command("restart", team, resource_id)


@frappe.whitelist(methods=["POST"])
@resource_action
def terminate_server(team: str | None = None, resource_id: str | None = None) -> dict:
	"""Terminate a server. Gated on `server:terminate`."""
	return _run_command("terminate", team, resource_id)


def _run_command(action: str, team: str | None, resource_id: str | None) -> dict:
	from central.resource_actions import submit_command

	return submit_command(action, team, resource_id)


@frappe.whitelist(methods=["POST"])
@resource_action
def create_server(
	team: str,
	region: str,
	title: str,
	offering: str,
	image_id: str,
	request_key: str,
	plan: str,
	hostname: str | None = None,
	ssh_keys: list[str] | None = None,
) -> dict:
	from central.server_provisioning import submit_request

	return submit_request(
		team=team,
		region=region,
		title=title,
		offering=offering,
		image_id=image_id,
		request_key=request_key,
		plan=plan,
		hostname=hostname,
		ssh_keys=ssh_keys,
	)


@frappe.whitelist(methods=["POST"])
@resource_action
def create_composed_server(
	team: str,
	region: str,
	title: str,
	offering: str,
	image_id: str,
	request_key: str,
	includes: list[dict],
	sub_category: str,
	hostname: str | None = None,
	ssh_keys: list[str] | None = None,
) -> dict:
	from central.server_provisioning import submit_request

	return submit_request(
		team=team,
		region=region,
		title=title,
		offering=offering,
		image_id=image_id,
		request_key=request_key,
		includes=includes,
		sub_category=sub_category,
		hostname=hostname,
		ssh_keys=ssh_keys,
	)


@frappe.whitelist(methods=["GET"])
def action_status(name: str) -> dict:
	from central.resource_actions import get_status

	return get_status(name)


@frappe.whitelist(methods=["POST"])
@resource_action
def retry_action(name: str) -> dict:
	"""Send a failed creation again on its own record. Gated on `server:create`."""
	from central.resource_actions import retry

	return retry(name)
