from __future__ import annotations

import frappe
from frappe import _

from central.errors import handle_resource_operation
from central.infrastructure.doctype.resource_action.resource_action import ResourceAction
from central.integrations.servers import reconcile
from central.utils.guards import require_capability

# Server endpoints for the console. Reads come from the VirtualMachine mirror; commands go
# to Atlas as the operator (Atlas stays policy-unaware — capability gating happens
# here). Every call resolves and authorizes a team first.

# `list_instances` reads only these non-secret Region fields — base_url, atlas_region_id
# and webhook_secret never leave this allowlist for a non-operator caller.
REGION_LIST_FIELDS = (
	"region",
	"status",
	"reachable",
	"display_name",
	"provider",
	"country_code",
	"latitude",
	"longitude",
)


@frappe.whitelist(methods=["GET"])
@require_capability("server:view", "You can't view this team's servers.")
def registry(team: str | None = None) -> dict:
	"""List a team's VMs — servers (the VirtualMachine mirror) and self-serve sites (the Site
	mirror, each a 1:1-backed VM) — in one read, so the console's map/panel unify them
	from a single call. A pure read; gated on `server:view`. Terminated sites are gone,
	not a state to render, so they're excluded here (Terminated servers are filtered by
	the map feed client-side)."""
	servers = frappe.get_list(
		"Virtual Machine",
		filters={"team": team},
		fields=[
			"name",
			"resource_id",
			"title",
			"region",
			"status",
			"plan",
			"frappe_version",
			"vcpus",
			"memory_megabytes",
			"disk_gigabytes",
			"ipv6_address",
			"public_ipv4",
			"gateway_url",
			"state_observed_at",
		],
		order_by="region asc, resource_id asc",
		limit_page_length=0,
	)
	# Overlay the transitional label of any in-flight action, so a just-clicked
	# start/stop/terminate (or a still-provisioning create) reads as "…ing" until the
	# mirror catches up — instead of looking like nothing happened.
	pending = ResourceAction.pending_labels(team)
	for server in servers:
		server["pending_action"] = pending.get(server["resource_id"])

	# A creation has no server row until the region accepts it, so it cannot be overlaid
	# like the pending actions above. It rides here as its own list: the console picks its
	# own request back up after a reload, and the fleet can show what is still building.
	creations = ResourceAction.open_creations(team)

	rows = frappe.get_list(
		"Site", filters={"team": team}, fields=["name", "server"], order_by="name asc", limit_page_length=0
	)
	return {"team": team, "servers": servers, "sites": _sites(rows, servers, pending), "creations": creations}


def _sites(rows: list[dict], servers: list[dict], pending: dict[str, str]) -> list[dict]:
	"""A site is a VM too, so it lists beside the servers and reads the same way.

	Its address is its name and its state is its machine's, so both are read here from the
	machines this call already loaded. A terminated machine is gone, not a state to render,
	so its site goes with it."""
	machines = {server["name"]: server for server in servers}
	return [
		{
			"name": row["name"],
			"subdomain": row["name"].split(".")[0],
			"server": row["server"],
			"url": f"https://{row['name']}",
			"status": machine["status"],
			"region": machine["region"],
			# A site's actions run against its machine, so its in-flight label is the machine's.
			"pending_action": pending.get(row["server"]),
		}
		for row in rows
		if (machine := machines.get(row["server"])) and machine["status"] != "Terminated"
	]


@frappe.whitelist(methods=["GET"])
@require_capability("server:view", "You can't view this team's servers.")
def server_overview(team: str | None = None, resource_id: str | None = None) -> dict:
	"""Return one server's Central mirror plus Pilot's cached operational metrics."""
	if not resource_id:
		frappe.throw(_("resource_id is required."), frappe.ValidationError)

	row = _overview_server_row(resource_id, team)
	if not row:
		frappe.throw(_("No server '{0}' for this team.").format(resource_id), frappe.DoesNotExistError)

	server = frappe._dict(
		{
			"resource_id": row.resource_id,
			"title": row.title,
			"region": row.region,
			"status": row.status,
			"plan": row.plan,
			"frappe_version": row.frappe_version,
			"image_offering": row.image_offering,
			"vcpus": row.vcpus,
			"memory_megabytes": row.memory_megabytes,
			"disk_gigabytes": row.disk_gigabytes,
			"ipv6_address": row.ipv6_address,
			"public_ipv4": row.public_ipv4,
			"ssh_command": f"ssh ubuntu@{row.public_ipv4}"
			if row.image_offering == "ubuntu" and row.public_ipv4
			else None,
			"gateway_url": row.gateway_url,
			"creation": row.creation,
		}
	)
	return {
		"server": {
			**server,
			**_overview_plan(server, team),
			"team_name": row.team_name or team,
			"region_details": {
				"display_name": row.region_display_name or server.region,
				"provider": row.region_provider,
				"country_code": row.region_country_code,
			},
		},
		"monitoring": _server_monitoring(server, audience_id=row.audience_id),
	}


@frappe.whitelist(methods=["GET"])
@require_capability("server:view", "You can't view this team's servers.")
def server_hostnames(team: str | None = None, resource_id: str | None = None) -> list[dict]:
	"""The site and custom-domain hostnames a server answers. They stop working when the
	server is terminated, so the console lists them before it asks. Gated on `server:view`."""
	server = frappe.db.get_value("Virtual Machine", {"team": team, "resource_id": resource_id}, "name")
	if not server:
		frappe.throw(_("No server '{0}' for this team.").format(resource_id), frappe.DoesNotExistError)

	sites = frappe.get_list("Site", filters={"team": team, "server": server}, pluck="name")
	routes = frappe.get_list(
		"Site Domain",
		filters={"team": team, "server": server},
		fields=["domain", "route_type"],
		order_by="domain asc",
	)
	hostnames = [{"hostname": site, "kind": "Site"} for site in sites]
	hostnames += [
		{"hostname": route.domain, "kind": "Site" if route.route_type == "Site" else "Custom domain"}
		for route in routes
		if route.domain not in sites
	]
	return hostnames


def _overview_server_row(resource_id: str, team: str):
	"""VirtualMachine + region + team + active Pilot audience in one query."""
	server = frappe.qb.DocType("Virtual Machine")
	region = frappe.qb.DocType("Region")
	team_table = frappe.qb.DocType("Team")
	pilot = frappe.qb.DocType("Pilot Credential")
	rows = (
		frappe.qb.from_(server)
		# VirtualMachine.region links straight to Region.
		.left_join(region)
		.on(region.name == server.region)
		.left_join(team_table)
		.on(team_table.name == server.team)
		.left_join(pilot)
		.on((pilot.server == server.name) & (pilot.status == "Active"))
		.select(
			server.resource_id,
			server.title,
			server.region,
			server.status,
			server.plan,
			server.frappe_version,
			server.image_offering,
			server.vcpus,
			server.memory_megabytes,
			server.disk_gigabytes,
			server.ipv6_address,
			server.public_ipv4,
			server.gateway_url,
			server.creation,
			region.display_name.as_("region_display_name"),
			region.provider.as_("region_provider"),
			region.country_code.as_("region_country_code"),
			team_table.team_name.as_("team_name"),
			pilot.audience_id.as_("audience_id"),
		)
		.where((server.resource_id == resource_id) & (server.team == team))
		.limit(1)
		.run(as_dict=True)
	)
	return rows[0] if rows else None


def _overview_plan(server: dict, team: str) -> dict:
	"""Tier name + billed rate — scoped to this server, not the team's full run-rate.

	Reads the server's open priced segment through the billing seam
	(`active_segment_for_resource`) rather than querying Subscription / Subscription
	Change and re-deriving the ledger's open-segment rule here — servers does not own
	how a segment resolves from the billing ledger."""
	from central.billing.catalog.subscriptions import active_segment_for_resource

	currency = frappe.db.get_value("Billing Profile", team, "currency") or "INR"
	billing_cycle = "Monthly"
	title = None
	rate = None
	plan_name = server.plan

	segment = active_segment_for_resource(server.resource_id)
	if segment:
		plan_name = segment.plan or plan_name
		# Only adopt the segment's currency/rate once a plan is attached: a Virtual Machine can
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
				rate = frappe.get_cached_doc("Plan", plan_name).get_rate(currency, server.region)
	else:
		# VirtualMachine bootstrap may open a Subscription before a plan is attached — no rate to show.
		rate = None

	return {
		"plan_title": title,
		"plan_rate": rate,
		"plan_currency": currency,
		"plan_billing_cycle": billing_cycle,
	}


def _server_monitoring(server: dict, audience_id: str | None = None) -> dict:
	"""Pilot metrics are meaningful only for a live, enrolled bench VM."""
	if server.status != "Running" or not server.gateway_url or not audience_id:
		return {"available": False}

	from central.integrations.pilot import get_cached_monitoring

	return get_cached_monitoring(server.resource_id, server.gateway_url, audience_id)


@frappe.whitelist(methods=["GET"])
@require_capability("cluster:view", "You can't view clusters for this team.")
def list_instances(team: str | None = None) -> list[dict]:
	"""List the regions a team can place servers in — every Active Region.
	A pure read for the console's New Server region picker. Gated on `cluster:view`
	(same scope as `registry`); the team only resolves the gate, the region set is
	team-agnostic."""
	# Region carries Atlas's credentials (base_url, webhook_secret, atlas_region_id),
	# so the DocType is locked to System Manager. `cluster:view` already authorizes
	# this read, so we bypass DocType RBAC and read only the non-secret allowlist —
	# otherwise a Central User (e.g. a team Owner) gets an empty list.
	return frappe.get_all(
		"Region",
		filters={"status": "Active"},
		fields=list(REGION_LIST_FIELDS),
		order_by="region asc",
	)


@frappe.whitelist(methods=["POST"])
@require_capability("server:view", "You can't refresh this team's servers.")
def refresh_servers(team: str | None = None) -> dict:
	"""Manually reconcile this team's mirror from every Active Atlas — the on-demand
	twin of the scheduled reconcile. Gated on `server:view`."""
	return reconcile(team)


@frappe.whitelist(methods=["POST"])
@handle_resource_operation
def start_server(team: str | None = None, resource_id: str | None = None) -> dict:
	"""Start a stopped server. Gated on `server:power`."""
	return _run_command("start", team, resource_id)


@frappe.whitelist(methods=["POST"])
@handle_resource_operation
def stop_server(team: str | None = None, resource_id: str | None = None) -> dict:
	"""Stop a running server. Gated on `server:power`."""
	return _run_command("stop", team, resource_id)


@frappe.whitelist(methods=["POST"])
@handle_resource_operation
def restart_server(team: str | None = None, resource_id: str | None = None) -> dict:
	"""Restart a running server. Gated on `server:power`."""
	return _run_command("restart", team, resource_id)


@frappe.whitelist(methods=["POST"])
@handle_resource_operation
@require_capability("server:resize", "You can't resize this team's servers.")
def resize_server(
	team: str | None = None,
	resource_id: str | None = None,
	plan: str | None = None,
	includes: list | str | None = None,
	sub_category: str | None = None,
	disk_gigabytes: int | None = None,
) -> dict:
	"""Resize a server's CPU, memory, and disk.

	Gated on `server:resize`. Billing re-locks the rate and Atlas applies the
	shape: a compute change stops the server first, a larger disk does not, and
	a smaller disk is refused. Atlas moves the server if this host cannot fit it."""
	if not resource_id:
		frappe.throw(_("A server is required."))

	server = frappe.db.get_value("Virtual Machine", {"team": team, "resource_id": resource_id}, "name")
	if not server:
		frappe.throw(_("Server {0} was not found.").format(resource_id), frappe.DoesNotExistError)
	subscription = frappe.db.get_value("Subscription", {"team": team, "server_id": server}, "name")
	if not subscription:
		frappe.throw(_("This server has no subscription to resize."))

	from central.billing.catalog.subscriptions import begin_resize

	if isinstance(includes, str):
		includes = frappe.parse_json(includes)
	if disk_gigabytes is not None and disk_gigabytes != "":
		disk_gigabytes = frappe.utils.cint(disk_gigabytes)
	else:
		disk_gigabytes = None
	result = begin_resize(
		subscription,
		plan=plan or None,
		includes=includes,
		sub_category=sub_category or None,
		disk_gigabytes=disk_gigabytes,
	)
	return {"subscription": subscription, **result}


@frappe.whitelist(methods=["POST"])
@handle_resource_operation
def terminate_server(
	team: str | None = None, resource_id: str | None = None, take_snapshot: bool | int | str = False
) -> dict:
	"""Terminate a server. Gated on `server:terminate`. With `take_snapshot`, it first takes
	a final snapshot, which also needs `server:snapshot`."""
	return _run_command("terminate", team, resource_id, take_snapshot=bool(frappe.utils.cint(take_snapshot)))


def _run_command(action: str, team: str | None, resource_id: str | None, take_snapshot: bool = False) -> dict:
	from central.resource_actions import submit_command

	return submit_command(action, team, resource_id, take_snapshot=take_snapshot)


@frappe.whitelist(methods=["POST"])
@handle_resource_operation
def create_server(
	team: str,
	region: str,
	title: str,
	request_key: str,
	plan: str,
	offering: str = "",
	image_id: str = "",
	hostname: str | None = None,
	ssh_keys: list[str] | None = None,
	ssh_key_ids: list[str] | None = None,
	snapshot: str | None = None,
) -> dict:
	"""Create a server from an image, or restore one from a `snapshot`."""
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
		ssh_key_ids=ssh_key_ids,
		snapshot=snapshot,
	)


@frappe.whitelist(methods=["POST"])
@handle_resource_operation
def create_composed_server(
	team: str,
	region: str,
	title: str,
	request_key: str,
	includes: list[dict],
	sub_category: str,
	offering: str = "",
	image_id: str = "",
	hostname: str | None = None,
	ssh_keys: list[str] | None = None,
	ssh_key_ids: list[str] | None = None,
	snapshot: str | None = None,
) -> dict:
	"""Create a custom-sized server from an image, or restore one from a `snapshot`."""
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
		ssh_key_ids=ssh_key_ids,
		snapshot=snapshot,
	)


@frappe.whitelist(methods=["GET"])
def action_status(name: str) -> dict:
	from central.resource_actions import get_status

	return get_status(name)


@frappe.whitelist(methods=["POST"])
@handle_resource_operation
def retry_action(name: str) -> dict:
	"""Send a failed creation again on its own record. Gated on `server:create`."""
	from central.resource_actions import retry

	return retry(name)
