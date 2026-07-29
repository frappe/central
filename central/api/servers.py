from __future__ import annotations

import re
import unicodedata

import frappe
from frappe import _

from central.iam import can, resolve_team
from central.integrations.atlas import AtlasClient, reconcile

# Server endpoints for the console. Reads come from the Asset mirror; commands go
# to Atlas as the operator (Atlas stays policy-unaware — capability gating happens
# here). Every call resolves and authorizes a team first.

# `list_instances` merges an Active Atlas Instance's liveness with its Region's
# display metadata. Only these non-secret Atlas Instance fields are ever read —
# the credentials/tunnel internals (api_key/api_secret/base_url/tunnel_*/peer_*/
# service_user) now sit apart from the map metadata, which lives on Region.
INSTANCE_LIVENESS_FIELDS = ("region", "status", "reachable")
REGION_DISPLAY_FIELDS = ("display_name", "provider", "country_code", "latitude", "longitude")

# Fallback version list for the new-server form when no Atlas is reachable. The
# authoritative set is derived live from Atlas's active bench images (which token
# maps to which image is Atlas's concern) — see `frappe_versions`.
FALLBACK_FRAPPE_VERSIONS = ("v16", "v15", "nightly")
ASSET_TITLE_MAX_LENGTH = 140
RESERVED_SERVER_ADDRESSES = frozenset(
	{"www", "admin", "api", "proxy", "app", "dashboard", "mail", "ns", "root"}
)

# Staging trials: a team flagged `is_staging_trial` provisions on its free welcome credits
# without a full billing profile, up to TRIAL_SERVER_LIMIT servers. Size and price come
# from the chosen catalog plan (the same as a normal create); which plans a trial may
# pick — the entry tiers — is a front-end concern in the New Server form.
TRIAL_SERVER_LIMIT = 3


def _available_versions(region: str | None = None) -> list[str]:
	"""The versions Atlas can provision in `region` (its active bench images). Regions
	can expose different images, so this must be scoped to the region the user picked —
	validating against a different region would reject valid creates or pass ones the
	target can't provision. Falls back to the first Active region when none is given
	(the picker's initial load), and to the static set when no Atlas is reachable."""
	target = region or frappe.db.get_value(
		"Atlas Instance", {"status": "Active"}, "name", order_by="region asc"
	)
	if target:
		try:
			versions = AtlasClient.for_region(target).available_frappe_versions()
			if versions:
				return versions
		except Exception:
			frappe.log_error(title="frappe_versions: Atlas unreachable, using fallback")
	return list(FALLBACK_FRAPPE_VERSIONS)


def _validate_frappe_version(frappe_version: str | None, region: str | None = None) -> None:
	# Validate against the CHOSEN region's images, not a random active one.
	if not frappe_version:
		return
	versions = _available_versions(region)
	# The client value never goes back into the message — frappe.throw renders HTML in
	# desk, so reflecting input is an XSS habit not worth having.
	if frappe_version not in versions:
		frappe.throw(
			_("Unknown Frappe version. Choose one of: {0}.").format(", ".join(versions)),
			frappe.ValidationError,
		)


def _stamp_frappe_version(resource_id: str | None, frappe_version: str | None) -> None:
	"""Record on the Pending Asset the version Atlas actually provisioned (echoed in
	the create reply / events), not merely what was requested. `Asset._stamp` keeps it
	current from later events."""
	if resource_id and frappe_version and frappe.db.exists("Asset", resource_id):
		frappe.db.set_value("Asset", resource_id, "frappe_version", frappe_version)


def _server_names(title: str | None, subdomain: str | None) -> tuple[str, str]:
	"""Return the Central label and Atlas-safe address for a new server."""
	friendly_title = (title or "").strip()
	if len(friendly_title) > ASSET_TITLE_MAX_LENGTH:
		frappe.throw(
			_("Server name must be at most {0} characters.").format(ASSET_TITLE_MAX_LENGTH),
			frappe.ValidationError,
		)
	address_source = friendly_title or "server" if subdomain is None else subdomain
	atlas_title = _slugify_subdomain(address_source)
	if atlas_title in RESERVED_SERVER_ADDRESSES:
		frappe.throw(_("Server address is reserved. Choose another."), frappe.ValidationError)
	return friendly_title or atlas_title, atlas_title


def _slugify_subdomain(value: str | None) -> str:
	"""Convert user input into one DNS label accepted by Atlas."""
	text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
	slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:63].rstrip("-")
	if not slug:
		frappe.throw(
			_("Server address must include at least one letter or number."),
			frappe.ValidationError,
		)
	return slug


def _mirror_provisioned_vm(region: str, vm: dict, friendly_title: str) -> str | None:
	"""Mirror Atlas's reply while retaining Central's user-facing server name."""
	resource_id = vm.get("name")
	if not resource_id:
		return None
	from central.central.doctype.asset.asset import Asset

	Asset.mirror_vm(region, vm, friendly_title=friendly_title)
	_stamp_frappe_version(resource_id, vm.get("frappe_version"))
	return resource_id


@frappe.whitelist(methods=["GET"])
def frappe_versions(region: str | None = None) -> list[str]:
	"""Versions offered on the new-server form for `region` — derived from that
	region's active bench images, so the picker never drifts from what can actually
	be provisioned there. The form passes the picked region and refetches on change."""
	return _available_versions(region)


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

	assets = frappe.get_all(
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
			"last_synced_at",
		],
		order_by="cluster asc, resource_id asc",
	)
	# A site is a VM too — flat and uncapped, symmetric with servers. `name` is the FQDN
	# (the stable id + terminate key); `subdomain` is the user-entered display name.
	sites = frappe.get_all(
		"Site",
		filters={"team": team, "status": ["!=", "Terminated"]},
		fields=["name", "subdomain", "status", "url", "region"],
		order_by="subdomain asc",
	)
	return {"team": team, "assets": assets, "sites": sites}


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
	"""Tier name + billed rate — scoped to this asset, not the team's full run-rate."""
	currency = frappe.db.get_value("Billing Profile", team, "currency") or "INR"
	billing_cycle = "Monthly"
	title = None
	rate = None
	plan_name = asset.plan

	subscription = frappe.qb.DocType("Subscription")
	change = frappe.qb.DocType("Subscription Change")
	segment_rows = (
		frappe.qb.from_(subscription)
		.left_join(change)
		.on(
			(change.subscription == subscription.name)
			& (change.change_type.isin(("Created", "Plan Changed", "Cancelled")))
		)
		.select(
			subscription.plan,
			change.change_type,
			change.locked_rate,
			change.currency,
			change.effective_at,
			change.creation,
		)
		.where(subscription.asset_id == asset.resource_id)
		.orderby(change.effective_at, order=frappe.qb.desc)
		.orderby(change.creation, order=frappe.qb.desc)
		.limit(1)
		.run(as_dict=True)
	)
	if segment_rows:
		segment = segment_rows[0]
		plan_name = segment.plan or plan_name
		if segment.change_type and segment.change_type != "Cancelled":
			if segment.locked_rate is not None:
				rate = frappe.utils.flt(segment.locked_rate)
			currency = segment.currency or currency

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


def _is_staging_trial_team(team: str) -> bool:
	return bool(frappe.db.get_value("Team", team, "is_staging_trial"))


def _require_trial_provisioning(team: str, plan: str | None) -> None:
	"""Trial teams provision on free welcome credits instead of a full billing profile:
	they need a billing currency, a plan (so usage meters against the credits), unspent
	credits, and room under the server cap. Size/price come from the plan, exactly as a
	normal create; the New Server form is what limits a trial to the entry tiers."""
	from central.billing.revenue.credits import get_balance

	if not plan:
		frappe.throw(_("Pick a plan to create a trial server."), frappe.ValidationError)
	if not frappe.db.get_value("Billing Profile", team, "currency"):
		frappe.throw(_("Set up your team's billing currency before creating servers."), frappe.ValidationError)
	if get_balance(team).get("balance", 0) <= 0:
		frappe.throw(
			_("Your trial credits are used up. Add a payment method to keep creating servers."),
			frappe.ValidationError,
		)
	running = frappe.db.count("Asset", {"team": team, "status": ["!=", "Terminated"]})
	if running >= TRIAL_SERVER_LIMIT:
		frappe.throw(_("Trial teams can run up to {0} servers.").format(TRIAL_SERVER_LIMIT), frappe.ValidationError)


@frappe.whitelist(methods=["POST"])
def create_server(
	team: str | None = None,
	region: str | None = None,
	title: str | None = None,
	plan: str | None = None,
	vcpus: int | None = None,
	memory_megabytes: int | None = None,
	disk_gigabytes: int | None = None,
	cpu_max_cores: float | None = None,
	frappe_version: str | None = None,
	subdomain: str | None = None,
) -> dict:
	"""Provision a new server for a team in a region from a preset bundle Plan. Gated
	on `server:create`.

	`region` is an Atlas Instance (one Atlas = one region), which is also how we
	route the provision call. Atlas owns placement/image/lifecycle; we pass the team
	(the tenant key) and the chosen size.

	Once the VM is created we record the billing Subscription for `plan` — the same
	way `create_composed_server` records a composed one — so the bundle a server was
	provisioned from is captured and its price-lock opened (ADR 0006/0010). That
	writes a Pending Asset keyed on the VM's id; the `vm.created` event Atlas emits
	then reconciles that same Asset (keyed on `resource_id`) instead of racing to
	create a second one.

	Trial teams (staging) skip the billing-profile gate and pay from free welcome
	credits; size and price still come from the chosen plan like any other create."""
	from central.billing.catalog.subscriptions import provision_subscription

	user = frappe.session.user
	team = resolve_team(user, team)
	if not can(user, team, "server:create"):
		frappe.throw(_("You can't create servers for this team."), frappe.PermissionError)
	if _is_staging_trial_team(team):
		# Trial: free credits fund it, no full profile. Size/price come from the plan.
		_require_trial_provisioning(team, plan)
	else:
		# A server bills the team, so it needs a billing profile first.
		from central.billing.api.dashboard._shared import require_billing_profile

		require_billing_profile(team, "create servers")
	if not region:
		frappe.throw(_("Region is required."), frappe.ValidationError)
	_validate_frappe_version(frappe_version, region)
	friendly_title, atlas_title = _server_names(title, subdomain)

	client = AtlasClient.for_region(region)
	vm = client.create_vm(
		team=team,
		title=atlas_title,
		vcpus=int(vcpus or 1),
		memory_megabytes=int(memory_megabytes or 512),
		disk_gigabytes=int(disk_gigabytes or 10),
		cpu_max_cores=cpu_max_cores,
		frappe_version=frappe_version,
	)
	resource_id = vm.get("name")
	# Record the contract for the bundle. Guarded so a raw-size call (no plan) still
	# provisions a VM without a subscription, as before.
	subscription = None
	if plan:
		subscription = provision_subscription(team, region, plan, resource_id=resource_id).get("subscription")
	# Mirror the VM Atlas returned even when billing already inserted the Pending
	# Asset. Otherwise preset creates render the UUID/Pending shell until the next
	# reconcile, instead of the user-facing title/status Atlas already returned.
	resource_id = _mirror_provisioned_vm(region, vm, friendly_title)
	return {"resource_id": resource_id, "server": vm, "subscription": subscription}


@frappe.whitelist(methods=["POST"])
def create_composed_server(
	team: str | None = None,
	region: str | None = None,
	title: str | None = None,
	includes: list | str | None = None,
	sub_category: str | None = None,
	frappe_version: str | None = None,
	subdomain: str | None = None,
) -> dict:
	"""Provision a design-your-own config end-to-end (#84): create the Atlas VM from
	the chosen composition, then record the composed Subscription (#80) that bills it
	from its parts. The server is the gate — composition, profile bounds, and headroom
	are re-validated server-side (#81/#83) *before* the VM is created, so a request the
	client lets through is still refused and never leaves an orphan VM."""
	from central.billing.catalog.composition import (
		COMPUTE,
		DISK,
		MEMORY,
		composition_quantities,
		validate_composition,
	)
	from central.billing.catalog.pricing import resolve_config_rate
	from central.billing.catalog.subscriptions import (
		enforce_headroom,
		provision_composed_subscription,
	)

	user = frappe.session.user
	team = resolve_team(user, team)
	if not can(user, team, "server:create"):
		frappe.throw("You can't create servers for this team.", frappe.PermissionError)
	# A server bills the team, so it needs a billing profile first.
	from central.billing.api.dashboard._shared import require_billing_profile

	require_billing_profile(team, "create servers")
	if not region:
		frappe.throw("region is required.", frappe.ValidationError)
	if isinstance(includes, str):
		includes = frappe.parse_json(includes)
	_validate_frappe_version(frappe_version, region)
	friendly_title, atlas_title = _server_names(title, subdomain)

	# Validate the shape + cost before touching Atlas.
	validate_composition(sub_category, includes)
	currency = frappe.db.get_value("Billing Profile", team, "currency")
	enforce_headroom(team, resolve_config_rate(includes, currency, region))

	qty = composition_quantities(includes)
	client = AtlasClient.for_region(region)
	vm = client.create_vm(
		team=team,
		title=atlas_title,
		vcpus=int(qty.get(COMPUTE, 1)) or 1,
		memory_megabytes=int(qty.get(MEMORY, 0) * 1024) or 512,
		disk_gigabytes=int(qty.get(DISK, 0)) or 10,
		frappe_version=frappe_version,
	)
	resource_id = vm.get("name")
	provision_composed_subscription(team, region, includes, sub_category, resource_id=resource_id)
	resource_id = _mirror_provisioned_vm(region, vm, friendly_title)
	return {"resource_id": resource_id, "server": vm}


@frappe.whitelist(methods=["POST"])
def start_server(team: str | None = None, resource_id: str | None = None) -> dict:
	"""Start a stopped server. Gated on `server:power`."""
	return _run_command("start", "server:power", "start", team, resource_id)


@frappe.whitelist(methods=["POST"])
def stop_server(team: str | None = None, resource_id: str | None = None) -> dict:
	"""Stop a running server. Gated on `server:power`."""
	return _run_command("stop", "server:power", "stop", team, resource_id)


@frappe.whitelist(methods=["POST"])
def terminate_server(team: str | None = None, resource_id: str | None = None) -> dict:
	"""Terminate a server. Gated on `server:terminate`."""
	return _run_command("terminate", "server:terminate", "terminate", team, resource_id)


def _run_command(
	action: str, capability: str, atlas_method: str, team: str | None, resource_id: str | None
) -> dict:
	"""Shared lifecycle path (start/stop/terminate): gate on `capability`, confirm
	the asset belongs to the team, call Atlas, return the Task handle."""
	user = frappe.session.user
	team = resolve_team(user, team)
	if not can(user, team, capability):
		frappe.throw(_("You can't {0} servers for this team.").format(action), frappe.PermissionError)
	if not resource_id:
		frappe.throw(_("resource_id is required."), frappe.ValidationError)

	# The asset must be in this team's mirror — also how we route to its Atlas.
	asset = frappe.db.get_value(
		"Asset",
		{"resource_id": resource_id, "team": team},
		["cluster", "resize_in_progress"],
		as_dict=True,
	)
	if not asset:
		frappe.throw(_("No server '{0}' for this team.").format(resource_id), frappe.DoesNotExistError)

	# A resize power-cycles the VM in the background; a manual start/stop mid-flight would
	# race it. Terminate is still allowed — the user may want to abandon the machine.
	if asset.resize_in_progress and action in ("start", "stop"):
		frappe.throw(_("This server is resizing — you can {0} it once that finishes.").format(action))

	instance = frappe.get_doc("Atlas Instance", asset.cluster)
	task = AtlasClient(instance).vm_action(resource_id, atlas_method)
	return {"resource_id": resource_id, "task": task}
