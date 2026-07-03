from __future__ import annotations

import frappe
from frappe import _

from central.iam import can, resolve_team
from central.integrations.atlas import AtlasClient, reconcile

# Server endpoints for the console. Reads come from the Asset mirror; commands go
# to Atlas as the operator (Atlas stays policy-unaware — capability gating happens
# here). Every call resolves and authorizes a team first.

# The only Atlas Instance fields `list_instances` may return. The doctype holds
# per-instance API credentials and tunnel internals, so exposure is allowlisted —
# never add api_key/api_secret/base_url/tunnel_*/peer_*/service_user here.
INSTANCE_PUBLIC_FIELDS = (
	"region",
	"status",
	"reachable",
	"display_name",
	"provider",
	"latitude",
	"longitude",
	"country_code",
)

# Frappe versions a new VM can be provisioned with. Central validates the choice
# and passes it to Atlas verbatim; Atlas owns what each token maps to.
FRAPPE_VERSIONS = ("v15", "v16", "v14", "nightly")


def _validate_frappe_version(frappe_version: str | None) -> None:
	# The client value never goes back into the message — frappe.throw renders
	# HTML in desk, so reflecting input is an XSS habit not worth having.
	if frappe_version and frappe_version not in FRAPPE_VERSIONS:
		frappe.throw(
			_("Unknown Frappe version. Choose one of: {0}.").format(", ".join(FRAPPE_VERSIONS)),
			frappe.ValidationError,
		)


def _stamp_frappe_version(resource_id: str | None, frappe_version: str | None) -> None:
	"""Record the chosen version on the Pending Asset the billing seam wrote. The
	Atlas echo (`Asset._stamp`) keeps it current after that."""
	if resource_id and frappe_version and frappe.db.exists("Asset", resource_id):
		frappe.db.set_value("Asset", resource_id, "frappe_version", frappe_version)


@frappe.whitelist(methods=["GET"])
def frappe_versions() -> list[str]:
	"""Versions offered on the new-server form, newest-stable first."""
	return list(FRAPPE_VERSIONS)


@frappe.whitelist(methods=["GET"])
def registry(team: str | None = None) -> dict:
	"""List a team's VMs from the Asset mirror — a pure read. Gated on `server:view`."""
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
	return {"team": team, "assets": assets}


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
	# this read, so we bypass DocType RBAC and curate the safe, non-secret fields
	# here — otherwise a Central User (e.g. a team Owner) gets an empty list.
	return frappe.get_all(
		"Atlas Instance",
		filters={"status": "Active"},
		fields=list(INSTANCE_PUBLIC_FIELDS),
		order_by="region asc",
	)


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
	create a second one."""
	from central.billing.catalog.subscriptions import provision_subscription

	user = frappe.session.user
	team = resolve_team(user, team)
	if not can(user, team, "server:create"):
		frappe.throw(_("You can't create servers for this team."), frappe.PermissionError)
	if not region:
		frappe.throw(_("Region is required."), frappe.ValidationError)
	_validate_frappe_version(frappe_version)

	client = AtlasClient.for_region(region)
	# Seed the Atlas tenant (first use) with the team owner's email.
	email = frappe.db.get_value("Team", team, "owner_user")
	vm = client.create_vm(
		team=team,
		title=title or "server",
		vcpus=int(vcpus or 1),
		memory_megabytes=int(memory_megabytes or 512),
		disk_gigabytes=int(disk_gigabytes or 10),
		email=email,
		cpu_max_cores=cpu_max_cores,
		frappe_version=frappe_version,
	)
	resource_id = vm.get("name")
	# Record the contract for the bundle. Guarded so a raw-size call (no plan) still
	# provisions a VM without a subscription, as before.
	subscription = None
	if plan:
		subscription = provision_subscription(team, region, plan, resource_id=resource_id).get(
			"subscription"
		)
	_stamp_frappe_version(resource_id, frappe_version)
	return {"resource_id": resource_id, "server": vm, "subscription": subscription}


@frappe.whitelist(methods=["POST"])
def create_composed_server(
	team: str | None = None,
	region: str | None = None,
	title: str | None = None,
	includes: list | str | None = None,
	sub_category: str | None = None,
	frappe_version: str | None = None,
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
	from central.billing.catalog.subscriptions import enforce_headroom, provision_composed_subscription

	user = frappe.session.user
	team = resolve_team(user, team)
	if not can(user, team, "server:create"):
		frappe.throw("You can't create servers for this team.", frappe.PermissionError)
	if not region:
		frappe.throw("region is required.", frappe.ValidationError)
	if isinstance(includes, str):
		includes = frappe.parse_json(includes)
	_validate_frappe_version(frappe_version)

	# Validate the shape + cost before touching Atlas.
	validate_composition(sub_category, includes)
	currency = frappe.db.get_value("Billing Profile", team, "currency")
	enforce_headroom(team, resolve_config_rate(includes, currency, region))

	qty = composition_quantities(includes)
	client = AtlasClient.for_region(region)
	email = frappe.db.get_value("Team", team, "owner_user")
	vm = client.create_vm(
		team=team,
		title=title or "server",
		vcpus=int(qty.get(COMPUTE, 1)) or 1,
		memory_megabytes=int(qty.get(MEMORY, 0) * 1024) or 512,
		disk_gigabytes=int(qty.get(DISK, 0)) or 10,
		email=email,
		frappe_version=frappe_version,
	)
	resource_id = vm.get("name")
	provision_composed_subscription(team, region, includes, sub_category, resource_id=resource_id)
	_stamp_frappe_version(resource_id, frappe_version)
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


def _run_command(action: str, capability: str, atlas_method: str, team: str | None, resource_id: str | None) -> dict:
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
		"Asset", {"resource_id": resource_id, "team": team}, ["cluster", "resize_in_progress"], as_dict=True
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
