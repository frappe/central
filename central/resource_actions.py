from __future__ import annotations

import hashlib
import json
import math
import re

import frappe
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.serialization import load_ssh_public_key
from frappe import _
from frappe.query_builder.functions import Sum
from pydantic import ValidationError

from central.billing.catalog.composition import (
	COMPUTE,
	DISK,
	MEMORY,
	composition_quantities,
	validate_composition,
)
from central.billing.catalog.pricing import resolve_config_rate
from central.billing.catalog.server_plans import get_server_plans
from central.billing.doctype.billing_profile.billing_profile import (
	get_team_currency,
	require_billing_profile,
)
from central.iam import can, resolve_team
from central.infrastructure.doctype.resource_action.resource_action import (
	ACTION_CAPABILITIES,
	COMMAND_ACTIONS,
	PENDING_STATES,
	ResourceAction,
)
from central.integrations.images import selected_image, snapshot_image, snapshot_source
from central.server_models import ActionStatus, CreateServerInput, ServerCreation


def submit_request(
	*,
	team: str,
	region: str,
	title: str,
	offering: str,
	image_id: str,
	request_key: str,
	plan: str | None = None,
	includes: list[dict] | None = None,
	sub_category: str | None = None,
	hostname: str | None = None,
	ssh_keys: list[str] | None = None,
	ssh_key_ids: list[str] | None = None,
	has_public_ipv6: bool = False,
	is_firewall_enabled: bool = False,
	resource_type: str = "Server",
	subdomain: str | None = None,
	snapshot: str | None = None,
) -> dict:
	"""Authorize and persist intent before any remote mutation.

	Server and site requests use the same queued action. A restore passes `snapshot`;
	its offering and image come from the snapshot."""
	if snapshot:
		offering, image_id = snapshot_source(team, snapshot)

	server_input = _validate_server_input(
		team=team,
		region=region,
		title=title,
		offering=offering,
		image_id=image_id,
		request_key=request_key,
		plan=plan,
		includes=includes,
		sub_category=sub_category,
		hostname=hostname,
		ssh_keys=ssh_keys,
		ssh_key_ids=ssh_key_ids,
		has_public_ipv6=has_public_ipv6,
		is_firewall_enabled=is_firewall_enabled,
	)
	if not can(frappe.session.user, server_input.team, "server:create"):
		frappe.throw(_("You cannot create servers for this Team."), frappe.PermissionError)

	digest = _request_digest(server_input, resource_type, subdomain)
	# Serialize budget reservations and repeated submissions within one Team.
	frappe.db.get_value("Team", server_input.team, "name", for_update=True)
	if existing := _repeated_request(server_input, digest):
		return existing.customer_status()

	configuration, rate = _build_server_configuration(server_input, snapshot)
	return ResourceAction.queue(
		"create",
		server_input.team,
		server_input.region,
		server_input.title,
		resource_type=resource_type,
		subdomain=subdomain,
		request_payload=configuration.model_dump(),
		request_key=server_input.request_key,
		request_digest=digest,
		reserved_monthly_rate=rate,
	).customer_status()


def submit_command(
	action: str, team: str | None, resource_id: str | None, take_snapshot: bool = False
) -> ActionStatus:
	"""Authorize the specific operation and persist it before dispatch. Only a terminate can
	take a final snapshot first."""
	team = resolve_team(frappe.session.user, team)
	if action not in COMMAND_ACTIONS or not can(
		frappe.session.user, team, ACTION_CAPABILITIES[action], server=resource_id
	):
		frappe.throw(_("You cannot perform this server action."), frappe.PermissionError)
	if take_snapshot and (
		action != "terminate" or not can(frappe.session.user, team, "server:snapshot", server=resource_id)
	):
		frappe.throw(_("You cannot take a snapshot of this server."), frappe.PermissionError)
	if not isinstance(resource_id, str) or not resource_id:
		frappe.throw(_("Select a server."))

	server = frappe.get_doc("Virtual Machine", resource_id, for_update=True)
	if server.team != team:
		frappe.throw(_("This server belongs to another Team."), frappe.PermissionError)
	if not server.atlas_vm_id:
		frappe.throw(_("This server has no verified regional identity."))
	if action == "restart" and server.status != "Running":
		frappe.throw(_("Only a running server can be restarted."))

	document = ResourceAction.get_pending(server.name, action) or ResourceAction.queue(
		action,
		team,
		server.region,
		server.title or server.name,
		server=server.name,
		remote_vm_id=server.atlas_vm_id,
		take_snapshot=int(take_snapshot),
	)
	return document.customer_status()


def get_status(name: str) -> ActionStatus:
	document = frappe.get_doc("Resource Action", name)
	document.check_permission("read")
	return document.customer_status()


def retry(name: str) -> ActionStatus:
	"""Re-drive one action. The record owns permission and what is safe to send again."""
	return frappe.get_doc("Resource Action", name).retry()


def _validate_server_input(**values) -> CreateServerInput:
	"""Validate untrusted server creation values at the service boundary."""
	values["includes"] = values.get("includes") or []
	values["hostname"] = values.get("hostname") or ""
	values["ssh_keys"] = values.get("ssh_keys") or []
	values["ssh_key_ids"] = values.get("ssh_key_ids") or []
	try:
		server_input = CreateServerInput.model_validate(values)
	except ValidationError as error:
		detail = "; ".join(
			".".join(str(part) for part in item["loc"]) + ": " + item["msg"]
			for item in error.errors(include_input=False)
		)
		frappe.throw(_("Invalid server configuration: {0}").format(detail))

	if bool(server_input.plan) == bool(server_input.includes):
		frappe.throw(_("Choose either a plan or a custom configuration."))
	if len({row.resource_type for row in server_input.includes}) != len(server_input.includes):
		frappe.throw(_("Each resource type must occur once."))
	return server_input


def _request_digest(server_input: CreateServerInput, resource_type: str, subdomain: str | None) -> str:
	settings = server_input.model_dump(exclude={"request_key"})
	settings.update(resource_type=resource_type, subdomain=subdomain)
	return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()


def _repeated_request(server_input: CreateServerInput, digest: str):
	"""Return the action that already represents this customer request, if any."""
	name = frappe.db.get_value(
		"Resource Action",
		{"team": server_input.team, "request_key": server_input.request_key},
		for_update=True,
	)
	if name:
		action = frappe.get_doc("Resource Action", name)
		if action.request_digest != digest:
			frappe.throw(_("This request key was already used for different server settings."))
		return action

	name = unanswered_request(server_input.team, digest)
	return frappe.get_doc("Resource Action", name) if name else None


def _build_server_configuration(
	server_input: CreateServerInput, snapshot: str | None
) -> tuple[ServerCreation, float]:
	"""Resolve the authorized image, purchasable composition, and saved configuration."""
	image = (
		snapshot_image(server_input.team, server_input.region, snapshot, "server:create")
		if snapshot
		else selected_image(
			server_input.team,
			server_input.region,
			server_input.offering,
			server_input.image_id,
			"server:create",
		)
	)
	includes = [row.model_dump() for row in server_input.includes]
	composition, rate = validate_purchase(
		server_input.team,
		server_input.region,
		server_input.plan,
		includes,
		server_input.sub_category,
	)
	validate_guest_input(server_input, image)
	# Check the saved keys now so the form shows the error. Dispatch reads their text, which a
	# rotation can change before a retry.
	selected_keys = resolve_team_ssh_keys(server_input.team, server_input.ssh_key_ids)
	if image["tags"].get("purpose") != "pilot" and not (selected_keys or server_input.ssh_keys):
		frappe.throw(_("Select an SSH key for this server."))

	configuration = ServerCreation(
		offering=server_input.offering,
		image_id=server_input.image_id,
		plan=server_input.plan,
		currency=get_team_currency(server_input.team),
		billing_cycle=frappe.db.get_value("Plan", server_input.plan, "billing_cycle")
		if server_input.plan
		else "Monthly",
		includes=composition,
		sub_category=server_input.sub_category,
		hostname=server_input.hostname,
		ssh_keys=server_input.ssh_keys,
		ssh_key_ids=server_input.ssh_key_ids,
		has_public_ipv6=server_input.has_public_ipv6,
		is_firewall_enabled=server_input.is_firewall_enabled,
		image_tags=image["tags"],
		**image_shape(composition, image),
	)
	return configuration, rate


def unanswered_request(team: str, digest: str) -> str | None:
	"""The creation this requester already sent with these settings, that no region has
	answered yet.

	Central saves a request before it calls a region, so a lost reply leaves the record
	behind while the browser keeps nothing. Answering the repeat with that record is what
	stops one click, or one click and a reload, from building two servers. A request that
	already holds a VM identity has been answered and never matches, so a deliberate
	second server is still a second record."""
	return frappe.db.get_value(
		"Resource Action",
		{
			"team": team,
			"action": "create",
			"requested_by": frappe.session.user,
			"request_digest": digest,
			"status": ["in", PENDING_STATES],
			"remote_vm_id": ["is", "not set"],
		},
	)


def validate_purchase(
	team: str, region: str, plan: str | None, includes: list[dict] | None, sub_category: str | None
) -> tuple[list[dict], float]:
	trial = bool(frappe.db.get_value("Team", team, "is_staging_trial"))
	if trial:
		validate_trial(team)
	else:
		require_billing_profile(team, "create servers")

	catalog = get_server_plans(team, cluster=region)
	if plan:
		choices = [row for rows in catalog["plans"].values() for row in rows]
		selected = next((row for row in choices if row["plan"] == plan), None)
		if not selected:
			frappe.throw(_("This plan is not available for the selected Team and region."))
		composition, rate = selected["includes"], selected["rate"]
	else:
		if (
			trial
			or not catalog["rate_card"]
			or not any(p["sub_category"] == sub_category for p in catalog["profiles"])
		):
			frappe.throw(_("A custom configuration is not available for this Team and region."))
		validate_composition(sub_category, includes)
		composition = includes
		rate = float(resolve_config_rate(includes, catalog["currency"], region))

	if not trial and rate + reserved_rate(team) > catalog["available"]:
		frappe.throw(_("Pending server requests and this plan exceed your spending limit."))
	return composition, float(rate)


def reserved_rate(team: str) -> float:
	request = frappe.qb.DocType("Resource Action")
	rows = (
		frappe.qb.from_(request)
		.select(Sum(request.reserved_monthly_rate))
		.where(
			(request.team == team)
			& request.status.isin(PENDING_STATES)
			& (request.server.isnull() | (request.server == ""))
		)
	).run()
	return float(rows[0][0] or 0)


def validate_trial(team: str) -> None:
	from central.billing.revenue.credits import get_balance

	if get_balance(team).get("balance", 0) <= 0:
		frappe.throw(_("Your trial credits are used up. Add a payment method to continue."))
	servers = frappe.db.count("Virtual Machine", {"team": team, "status": ["!=", "Terminated"]})
	pending = frappe.db.count(
		"Resource Action",
		{"team": team, "status": ["in", PENDING_STATES], "server": ["is", "not set"]},
	)
	if servers + pending >= 3:
		frappe.throw(_("Trial Teams can have at most three active or pending servers."))


def image_shape(includes: list[dict], image: dict) -> dict[str, int]:
	quantities = composition_quantities(includes)
	values = (quantities.get(COMPUTE, 0), quantities.get(MEMORY, 0) * 1024, quantities.get(DISK, 0) * 1024)
	if any(not math.isfinite(value) or value <= 0 or int(value) != value for value in values):
		frappe.throw(_("Choose whole virtual CPUs and positive memory and disk sizes in MiB."))
	shape = dict(zip(("virtual_cpu_count", "memory_mib", "disk_mib"), map(int, values), strict=True))
	if shape["virtual_cpu_count"] > 32:
		frappe.throw(_("Choose at most 32 virtual CPUs."))
	if shape["disk_mib"] < image["rootfs_size_mib"]:
		frappe.throw(_("This plan's disk is smaller than the selected image."))
	return shape


def validate_guest_input(server_input: CreateServerInput, image: dict) -> None:
	if server_input.ssh_key_ids and server_input.ssh_keys:
		frappe.throw(_("Choose saved SSH keys or enter public keys, not both."))
	if server_input.hostname and not re.fullmatch(
		r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", server_input.hostname
	):
		frappe.throw(_("Use a valid lowercase guest hostname."))
	for key in server_input.ssh_keys:
		try:
			load_ssh_public_key(key.strip().encode())
		except (ValueError, TypeError, UnsupportedAlgorithm):
			frappe.throw(_("Enter a valid OpenSSH public key on each line."))


def resolve_team_ssh_keys(team: str, names: list[str]) -> list[str]:
	"""Resolve only public keys owned by the authorized Team."""
	if len(names) != len(set(names)):
		frappe.throw(_("Select each SSH key only once."))
	if not names:
		return []
	rows = frappe.get_list(
		"Team SSH Key", filters={"team": team, "name": ["in", names]}, fields=["name", "public_key"], limit=20
	)
	keys = {row.name: row.public_key for row in rows}
	if len(keys) != len(names):
		frappe.throw(_("One selected SSH key is unavailable to this Team."), frappe.PermissionError)
	return [keys[name] for name in names]
