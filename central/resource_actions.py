from __future__ import annotations

import hashlib
import json
import math

import frappe
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.serialization import load_ssh_public_key
from frappe import _
from frappe.query_builder.functions import Count, Sum
from frappe.utils import cint, flt
from pydantic import ValidationError

from central.billing.catalog.composition import (
	COMPUTE,
	DISK,
	MEMORY,
	composition_quantities,
	validate_composition,
)
from central.billing.catalog.entitlements import get_team_caps
from central.billing.catalog.pricing import resolve_config_rate
from central.billing.catalog.server_plans import get_server_plans
from central.billing.doctype.billing_profile.billing_profile import (
	get_team_currency,
	is_complete,
	require_billing_profile,
)
from central.billing.payments.settlement import has_paid_by_hand, is_behind_on_payment, wallet_funds
from central.billing.revenue.tax import is_internal_team
from central.errors import throw_action_error
from central.iam import can, resolve_team
from central.infrastructure.doctype.resource_action.resource_action import (
	ACTION_CAPABILITIES,
	COMMAND_ACTIONS,
	PENDING_STATES,
	ResourceAction,
)
from central.integrations.images import selected_image, snapshot_image, snapshot_source
from central.server_models import (
	DNS_LABEL,
	MAXIMUM_USER_DATA_BYTES,
	ActionStatus,
	CreateServerInput,
	ServerCreation,
	SiteCreation,
)
from central.signups.eligibility import (
	get_open_trial_summary,
	get_owner_team_names,
	has_active_payment_method,
	is_free_trial_creation,
)
from central.utils.units import MIB_PER_GIB, MILLICORES_PER_VCPU


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
	has_public_ipv4: bool = False,
	has_public_ipv6: bool = False,
	is_firewall_enabled: bool = False,
	user_data: str = "",
	resource_type: str = "Server",
	subdomain: str | None = None,
	snapshot: str | None = None,
	site: SiteCreation | None = None,
) -> dict:
	"""Authorize and persist intent before any remote mutation.

	Server and site requests use the same queued action. A restore passes `snapshot`;
	its offering and image come from the snapshot. A trial site passes `site`."""
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
		has_public_ipv4=has_public_ipv4,
		has_public_ipv6=has_public_ipv6,
		is_firewall_enabled=is_firewall_enabled,
		user_data=user_data,
	)
	if not can(frappe.session.user, server_input.team, "server:create"):
		frappe.throw(
			_("You cannot create servers for this Team. Ask a team admin to review your access."),
			frappe.PermissionError,
		)
	frappe.get_cached_doc("Central Settings").require_new_server_network_options(
		server_input.has_public_ipv4, server_input.has_public_ipv6, server_input.is_firewall_enabled
	)
	if server_input.has_public_ipv4:
		from central.billing.catalog.public_ips import require_public_ipv4_rate

		require_public_ipv4_rate(server_input.team, server_input.region)

	digest = _request_digest(server_input, resource_type, subdomain)
	# Serialize budget reservations and repeated submissions within one Team.
	frappe.db.get_value("Team", server_input.team, "name", for_update=True)
	if existing := _repeated_request(server_input, digest):
		return existing.customer_status()

	is_free_trial = is_free_trial_creation(server_input.team, site.product if site else None)
	configuration, rate = _build_server_configuration(server_input, snapshot, is_free_trial)
	configuration.site = site

	return ResourceAction.queue(
		"create",
		server_input.team,
		server_input.region,
		server_input.title,
		resource_type=resource_type,
		subdomain=subdomain,
		product=site.product if site else None,
		is_free_trial=int(is_free_trial),
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
		frappe.throw(
			_("You cannot perform this server action. Ask a team admin to review your access."),
			frappe.PermissionError,
		)
	if take_snapshot and (
		action != "terminate" or not can(frappe.session.user, team, "server:snapshot", server=resource_id)
	):
		frappe.throw(
			_("You cannot take a snapshot of this server. Ask a team admin to review your access."),
			frappe.PermissionError,
		)
	if not isinstance(resource_id, str) or not resource_id:
		frappe.throw(_("Select a server."))

	server = frappe.get_doc("Virtual Machine", resource_id, for_update=True)
	if server.team != team:
		frappe.throw(_("This server belongs to another Team."), frappe.PermissionError)
	if not server.atlas_vm_id:
		frappe.throw(
			_(
				"This server has no verified regional identity. Refresh its status before trying again. Contact support if the server remains unavailable."
			)
		)
	if action == "restart" and server.status != "Running":
		frappe.throw(_("Only a running server can be restarted."))
	if action == "start" and frappe.db.exists(
		"Subscription", {"server_id": server.name, "account_standing": "Suspended"}
	):
		throw_action_error(
			"PAYMENT_OVERDUE", message=_("This server is suspended because an invoice is unpaid.")
		)
	if action == "start" and frappe.db.exists("Site", {"server": server.name, "trial_state": "Ended"}):
		if has_active_payment_method(team):
			frappe.throw(_("This trial has ended. Choose Keep this site to start it on its paid plan."))
		frappe.throw(_("This trial has ended. Add a payment method to start it again."))
	if action == "terminate" and server.is_termination_protected:
		frappe.throw(_("Turn off termination protection before you terminate this server."))
	if take_snapshot:
		server.require_server_access()

	return _queue_command(action, server, take_snapshot=take_snapshot)


def submit_billing_command(action: str, server_name: str) -> ActionStatus:
	"""Stop or start a server for billing, as the system.

	Dunning stops a server that is not paid for, and a payment starts it again. The
	payment can arrive by webhook as Guest, or from a member without `server:power`,
	so no user capability applies here."""
	if action not in ("stop", "start"):
		raise ValueError(f"Billing cannot {action} a server")

	server = frappe.get_doc("Virtual Machine", server_name, for_update=True)
	if not server.atlas_vm_id:
		frappe.throw(_("Server {0} has no verified regional identity.").format(server.name))

	return _queue_command(action, server, requested_by="Administrator")


def _queue_command(
	action: str, server, take_snapshot: bool = False, requested_by: str | None = None
) -> ActionStatus:
	document = ResourceAction.get_pending(server.name, action) or ResourceAction.queue(
		action,
		server.team,
		server.region,
		server.title or server.name,
		server=server.name,
		remote_vm_id=server.atlas_vm_id,
		requested_by=requested_by,
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
	server_input: CreateServerInput, snapshot: str | None, is_free_trial: bool
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
		is_free_trial,
	)
	validate_guest_input(server_input)
	# Check the saved keys now so the form shows the error. Dispatch reads their text, which a
	# rotation can change before a retry.
	resolve_team_ssh_keys(server_input.team, server_input.ssh_key_ids)

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
		has_public_ipv4=server_input.has_public_ipv4,
		has_public_ipv6=server_input.has_public_ipv6,
		is_firewall_enabled=server_input.is_firewall_enabled,
		user_data=server_input.user_data,
		image_tags=image["tags"],
		**image_shape(composition, image),
	)

	return configuration, rate


def unanswered_request(team: str, digest: str) -> str | None:
	"""The creation this requester already sent with these settings that no region answered.
	Returning it stops a repeated click or a reload from building two servers."""
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
	team: str,
	region: str,
	plan: str | None,
	includes: list[dict] | None,
	sub_category: str | None,
	is_free_trial: bool = False,
) -> tuple[list[dict], float]:
	"""The composition and monthly rate of a server the team may buy. A free trial site is not
	bought, so only the trial limit applies to it."""
	internal = is_internal_team(team)
	trial = is_free_trial or (not internal and bool(frappe.db.get_value("Team", team, "is_staging_trial")))
	if is_free_trial:
		validate_trial_site(team)
	elif trial:
		validate_trial(team)

	catalog = get_server_plans(team, cluster=region, include_trial_plans=is_free_trial)
	if plan:
		choices = [row for rows in catalog["plans"].values() for row in rows]
		selected = next((row for row in choices if row["plan"] == plan), None)
		if not selected:
			frappe.throw(
				_(
					"This plan is not available for this team in the selected region. Choose another plan or region."
				)
			)
		composition, rate = selected["includes"], selected["rate"]
	else:
		if (
			trial
			or not catalog["rate_card"]
			or not any(p["sub_category"] == sub_category for p in catalog["profiles"])
		):
			frappe.throw(
				_(
					"Custom server sizes are not available for this team in the selected region. Choose a listed plan or another region."
				)
			)
		validate_composition(sub_category, includes)
		composition = includes
		rate = float(resolve_config_rate(includes, catalog["currency"], region))

	# A free trial site is not bought, and an internal team is not held to a trust tier.
	if is_free_trial or internal:
		return composition, float(rate)

	committed_rate = rate + reserved_rate(team)
	if not trial:
		require_payment_method_or_credit(team, committed_rate)
	if committed_rate > catalog["available"]:
		frappe.throw(
			_(
				"This plan and your pending server requests exceed your spending limit. Choose a smaller plan, or contact support to review your limit."
			)
		)
	require_server_slot(team)

	return composition, float(rate)


def require_server_slot(team: str) -> None:
	"""Refuse a server beyond the number the team's trust tier allows."""
	limit = get_team_caps(team).max_resource_count
	count = server_count(team)
	if count >= limit:
		throw_action_error("TRUST_TIER_LIMIT", limit=limit, count=count)


def require_payment_method_or_credit(team: str, rate: float) -> None:
	"""Refuse a server that neither credit nor a way to pay covers.

	1. A team with an overdue invoice, or a subscription Past Due or Suspended, buys nothing.
	2. Credit that covers the rate is enough.
	3. With Central Settings' payment method requirement off, a complete profile is enough.
	4. Otherwise the billing profile must be complete, and the team needs an active payment
	   method, or must be on Manual Checkout with one invoice already paid."""
	if is_behind_on_payment(team):
		throw_action_error("PAYMENT_OVERDUE")

	if wallet_funds(team, rate):
		return

	if not frappe.get_cached_value("Central Settings", "Central Settings", "require_payment_method"):
		require_billing_profile(team, "create servers")
		return

	if is_complete(team) and (has_active_payment_method(team) or has_paid_by_hand(team)):
		return

	throw_action_error("PAYMENT_METHOD_REQUIRED")


def reserved_rate(team: str) -> float:
	# A locking read sees requests committed after this transaction's snapshot, so a
	# create that waited on the Team lock counts the one that went first.
	request = frappe.qb.DocType("Resource Action")
	rows = (
		frappe.qb.from_(request)
		.select(Sum(request.reserved_monthly_rate))
		.where(
			(request.team == team)
			& request.status.isin(PENDING_STATES)
			& (request.server.isnull() | (request.server == ""))
		)
		.for_update()
	).run()

	return flt(rows[0][0])


def validate_trial(team: str) -> None:
	from central.billing.revenue.credits import lock_team_wallet

	if lock_team_wallet(team) <= 0:
		frappe.throw(_("Your trial credits are used up. Add a payment method to continue."))
	limit = cint(frappe.get_cached_value("Central Settings", "Central Settings", "trial_servers_per_team"))
	if server_count(team) >= limit:
		frappe.throw(_("Trial Teams can have at most {0} active or pending servers.").format(limit))


def validate_trial_site(team: str) -> None:
	"""Refuse a new free trial while the owner's open trials reach the limit, and name the open one."""
	limit = cint(frappe.get_cached_value("Central Settings", "Central Settings", "trial_servers_per_team"))
	if trial_site_count(team) < limit:
		return

	summary = get_open_trial_summary(team) or {}
	if summary.get("address"):
		throw_action_error("TRIAL_IN_PROGRESS", product=summary["product_title"], address=summary["address"])
	if summary.get("state") == "Setting up":
		throw_action_error("TRIAL_IN_PROGRESS", message=_("Your free trial site is still being set up."))
	throw_action_error("TRIAL_IN_PROGRESS", message=_("You already have an open free trial."))


def trial_site_count(team: str) -> int:
	"""Open trial sites, pending site creations, and provisioned servers whose site Central has not recorded yet, across every team of the team's owner. Locking reads, for the same reason as reserved_rate."""
	teams = get_owner_team_names(team)
	site = frappe.qb.DocType("Site")
	machine = frappe.qb.DocType("Virtual Machine")
	request = frappe.qb.DocType("Resource Action")

	sites = (
		frappe.qb.from_(site)
		.select(Count("*"))
		.where(site.team.isin(teams) & site.trial_state.isin(("Active", "Ended")))
		.for_update()
	).run()

	pending = (
		frappe.qb.from_(request)
		.select(Count("*"))
		.where(
			request.team.isin(teams)
			& (request.is_free_trial == 1)
			& request.status.isin(PENDING_STATES)
			& (request.server.isnull() | (request.server == ""))
		)
		.for_update()
	).run()

	started = (
		frappe.qb.from_(site)
		.select(site.server)
		.where(site.server.isnotnull() & site.trial_state.isnotnull() & (site.trial_state != ""))
	)
	unready = (
		frappe.qb.from_(request)
		.join(machine)
		.on(machine.name == request.server)
		.select(Count("*"))
		.where(
			request.team.isin(teams)
			& (request.is_free_trial == 1)
			& (request.action == "create")
			& (machine.status != "Terminated")
			& ~request.server.isin(started)
		)
		.for_update()
	).run()

	return sites[0][0] + pending[0][0] + unready[0][0]


def server_count(team: str) -> int:
	"""Active servers plus pending creations. Locking reads, for the same reason as reserved_rate."""
	machine = frappe.qb.DocType("Virtual Machine")
	request = frappe.qb.DocType("Resource Action")

	servers = (
		frappe.qb.from_(machine)
		.select(Count("*"))
		.where((machine.team == team) & (machine.status != "Terminated"))
		.for_update()
	).run()

	pending = (
		frappe.qb.from_(request)
		.select(Count("*"))
		.where(
			(request.team == team)
			& request.status.isin(PENDING_STATES)
			& (request.server.isnull() | (request.server == ""))
		)
		.for_update()
	).run()

	return servers[0][0] + pending[0][0]


def image_shape(includes: list[dict], image: dict) -> dict[str, int]:
	"""The Atlas shape for a composition. Atlas takes CPU in millicores, so a fraction of a
	vCPU, such as 1/8, is a CPU quota on one guest vCPU."""
	quantities = composition_quantities(includes)
	values = (
		quantities.get(COMPUTE, 0) * MILLICORES_PER_VCPU,
		quantities.get(MEMORY, 0) * MIB_PER_GIB,
		quantities.get(DISK, 0) * MIB_PER_GIB,
	)
	if any(not math.isfinite(value) or value <= 0 or int(value) != value for value in values):
		frappe.throw(_("Choose CPU in whole millicores and positive memory and disk sizes in MiB."))

	keys = ("cpu_millicores", "memory_mib", "disk_mib")
	shape = {key: int(value) for key, value in zip(keys, values, strict=True)}

	if not 100 <= shape["cpu_millicores"] <= 32000:
		frappe.throw(_("Choose between 0.1 and 32 virtual CPUs."))

	if shape["disk_mib"] < image["rootfs_size_mib"]:
		frappe.throw(
			_(
				"The selected image needs more disk space than this plan provides. Choose a plan with more storage."
			)
		)

	return shape


def validate_guest_input(server_input: CreateServerInput) -> None:
	if server_input.ssh_key_ids and server_input.ssh_keys:
		frappe.throw(_("Choose saved SSH Keys or enter public keys, not both."))
	if server_input.hostname and not DNS_LABEL.fullmatch(server_input.hostname):
		frappe.throw(_("Use a valid lowercase guest hostname."))
	if len(server_input.user_data.encode()) > MAXIMUM_USER_DATA_BYTES:
		frappe.throw(_("Keep the user data under 16 KiB."))

	for key in server_input.ssh_keys:
		try:
			load_ssh_public_key(key.strip().encode())
		except (ValueError, TypeError, UnsupportedAlgorithm):
			frappe.throw(_("Enter a valid OpenSSH public key on each line."))


def resolve_team_ssh_keys(team: str, names: list[str]) -> list[str]:
	"""Resolve only public keys owned by the authorized Team."""
	if len(names) != len(set(names)):
		frappe.throw(_("Select each SSH Key only once."))
	if not names:
		return []

	rows = frappe.get_list(
		"Team SSH Key", filters={"team": team, "name": ["in", names]}, fields=["name", "public_key"], limit=20
	)
	keys = {row.name: row.public_key for row in rows}
	if len(keys) != len(names):
		frappe.throw(_("One selected SSH Key is unavailable to this Team."), frappe.PermissionError)

	return [keys[name] for name in names]
