from __future__ import annotations

import time
from datetime import datetime
from itertools import pairwise

import frappe
from frappe import _
from pydantic import ValidationError

from central.central.doctype.activity_event.activity_event import ActivityEvent
from central.central.doctype.activity_event.tracked import CONSOLE
from central.errors import AtlasConnectionError, AtlasRejected, AtlasResourceGone, build_envelope
from central.iam import can_on_any_server
from central.infrastructure.doctype.site.site import Site
from central.infrastructure.doctype.virtual_machine import firewall
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.integrations.atlas import (
	OFFLOAD_OFF_SETTINGS,
	SLEEP_OFF_SETTINGS,
	AtlasClient,
	ConsoleMode,
)
from central.server_models import ComputeSettings, FirewallChange
from central.utils.units import (
	gigabytes_to_mebibytes,
	mebibytes_to_gigabytes,
	millicores_to_vcpus,
	vcpus_to_millicores,
)

# A resize may move the VM to another host, so the wait is generous enough to cover a migration.
POWER_WAIT_SECONDS = 15 * 60
POWER_POLL_SECONDS = 5
# Atlas attaches or detaches a public address in seconds; a slower change shows on the next read.
ADDRESS_WAIT_SECONDS = 30
ADDRESS_POLL_SECONDS = 2
METRICS_CACHE_SECONDS = 60
MIB = 1024 * 1024


def observe_server(server: VirtualMachine) -> str:
	"""Read the owning region and record what it reports about this Team's server."""
	client = get_client(server)
	try:
		remote = client.get_vm(server.atlas_vm_id)
	except AtlasResourceGone:
		server.record_terminated()
		server.settle_pending_action("Terminated")
		return "Terminated"

	if remote.get("id") != server.atlas_vm_id or remote.get("tenant_id") != client.tenant_id:
		raise AtlasConnectionError(_("Atlas returned a different server or Team."))

	state = remote.get("current_state")
	states = {
		"running": "Running",
		"stopped": "Stopped",
		"paused": "Paused",
		"unknown": "Provisioning",
		"pending": "Provisioning",
		"terminating": "Provisioning",
	}
	status = "Failed" if remote.get("error") else states.get(state)
	if not status:
		raise AtlasConnectionError(_("Atlas returned an unsupported server state."))

	compute, disk, network = remote.get("compute"), remote.get("disk"), remote.get("network")
	if not all(isinstance(value, dict) for value in (compute, disk, network)):
		raise AtlasConnectionError(_("Atlas returned incomplete server configuration."))

	if any(
		type(value) is not int or value <= 0
		for value in (compute.get("cpu_millicores"), compute.get("memory_mib"), disk.get("size_mib"))
	):
		raise AtlasConnectionError(_("Atlas returned invalid server resource sizes."))

	# The regional proxy derives a VM's admin hostname from its mesh address, so Central
	# builds the gateway itself. An unenrolled pilot has nothing to sign into yet.
	gateway = None
	if frappe.db.exists("Pilot Credential", {"server": server.name, "team": server.team, "status": "Active"}):
		gateway = frappe.get_cached_doc("Region", server.region).get_vm_gateway_url(network.get("mesh_ipv6"))

	server.record_observed_state(
		{
			"status": status,
			"vcpus": millicores_to_vcpus(compute["cpu_millicores"]),
			"memory_megabytes": compute["memory_mib"],
			"disk_gigabytes": mebibytes_to_gigabytes(disk["size_mib"]),
			"ipv6_address": network.get("mesh_ipv6"),
			"public_ipv4": network.get("public_ipv4"),
			# Atlas reports the guest's public IPv6 as a prefix. A /128 is one address.
			"public_ipv6": (network.get("public_ipv6") or "").removesuffix("/128") or None,
			"gateway_url": gateway,
			"has_ipv4_internet": bool(network.get("ipv4_internet_access")),
			"has_wireguard_access": bool(network.get("wireguard_gateway_access")),
			**firewall.get_observed_firewall(network),
		},
		frappe.utils.now_datetime(),
	)

	# A Pilot machine carries a site, and this report is where its address arrives.
	Site.create_once_addressable(server.name)
	server.settle_pending_action(status)
	if status == "Running" and gateway and not server.admin_domain_task:
		frappe.enqueue_doc(
			"Virtual Machine",
			server.name,
			"claim_admin_hostname",
			queue="short",
			enqueue_after_commit=True,
			job_id=f"admin-domain:{server.name}",
			deduplicate=True,
		)

	return status


def get_remote_server(server: VirtualMachine) -> dict:
	"""Read the server from its region, and refuse an answer about another server or Team."""
	client = get_client(server)
	remote = client.get_vm(server.atlas_vm_id)
	if remote.get("id") != server.atlas_vm_id or remote.get("tenant_id") != client.tenant_id:
		raise AtlasConnectionError(_("Atlas returned a different server or Team."))

	return remote


def get_compute_settings(server: VirtualMachine) -> ComputeSettings:
	"""Read the sleep and CPU burst settings, which only the region stores."""
	compute = get_remote_server(server).get("compute") or {}
	try:
		return ComputeSettings.model_validate(
			{field: compute.get(field) for field in ComputeSettings.model_fields}
		)
	except ValidationError as error:
		raise AtlasConnectionError(_("Atlas returned invalid compute settings.")) from error


def set_compute_settings(server: VirtualMachine, settings: ComputeSettings) -> dict[str, int | bool]:
	"""Send only the changed settings to the region, and return them. Safe to repeat."""
	current = get_compute_settings(server).model_dump()
	changes = {field: value for field, value in settings.model_dump().items() if value != current[field]}
	if changes:
		get_client(server).set_compute_settings(server.atlas_vm_id, changes)

	return changes


def is_offload_allowed(memory_mib: int, disk_mib: int) -> bool:
	"""Whether Atlas accepts deep sleep and coma for a server of this size: 4 GiB memory and
	50 GiB disk at most, because a larger VM takes too long to upload and wake."""
	return memory_mib <= 4096 and disk_mib <= 51200


def get_rescue_state(server: VirtualMachine) -> dict:
	"""Read rescue state without changing Central's mirror or contacting the guest."""
	remote = get_remote_server(server)
	fields = ("is_rescue_mode_enabled", "is_in_rescue_mode")
	if any(
		field not in remote or (remote[field] is not None and type(remote[field]) is not bool)
		for field in fields
	):
		raise AtlasConnectionError(_("Atlas returned an invalid rescue state."))

	return {field: remote[field] for field in fields}


def set_rescue_mode(server: VirtualMachine, enabled: bool) -> None:
	"""Change only the boot selection; power remains a separate user action."""
	from central.errors import AtlasRequestUncertain, throw_action_error

	try:
		get_client(server).set_rescue_mode(server.atlas_vm_id, enabled)
	except AtlasRequestUncertain:
		throw_action_error(
			"OUTCOME_UNKNOWN",
			remediation=_("Refresh rescue status before submitting another request."),
		)


def resize_server(server: VirtualMachine, shape: dict) -> None:
	"""Apply a new size on Atlas, then start the server. Safe to repeat: every call sets
	absolute values. A CPU or memory change stops the server first; a disk-only grow does not.
	Sleep stays as the owner set it, and ends when the server leaves its trial plan. Deep sleep
	and coma go off when the new size is too large."""
	from central.billing.catalog.trials import is_trial_plan

	client = get_client(server)
	remote = client.get_vm(server.atlas_vm_id)
	compute, disk = remote.get("compute") or {}, remote.get("disk") or {}

	cpu_millicores = vcpus_to_millicores(shape["vcpus"])
	memory_mib = shape["memory_megabytes"]
	disk_mib = gigabytes_to_mebibytes(shape["disk_gigabytes"])

	is_reshaping = (compute.get("cpu_millicores"), compute.get("memory_mib")) != (cpu_millicores, memory_mib)
	is_sleepy = any(compute.get(field) for field in SLEEP_OFF_SETTINGS)
	rescue_selected = remote.get("is_rescue_mode_enabled") is True
	in_rescue = remote.get("is_in_rescue_mode") is True
	if (is_reshaping and (rescue_selected or in_rescue)) or (in_rescue and is_sleepy):
		error = AtlasRejected(_("This resize cannot complete in rescue mode."))
		error.envelope = build_envelope(
			"ATLAS_REJECTED",
			message=str(error),
			remediation=_("Disable rescue mode and boot normally before making this resize."),
		)
		raise error

	# The server keeps its trial plan until billing confirms the resize, so a resize from a trial plan
	# is the move off the trial, and the server stops sleeping. Otherwise sleep stays, but Atlas checks
	# the deep sleep and coma size limit against the new size, so those go off first when it is too large.
	is_offloading = any(compute.get(field) for field in OFFLOAD_OFF_SETTINGS)
	if is_trial_plan(server.plan) and is_sleepy:
		client.set_compute_settings(server.atlas_vm_id, SLEEP_OFF_SETTINGS)
	elif is_offloading and not is_offload_allowed(memory_mib, disk_mib):
		client.set_compute_settings(server.atlas_vm_id, OFFLOAD_OFF_SETTINGS)

	if is_reshaping:
		# Atlas refuses to stop a sleeping VM, so wake it first.
		if remote.get("current_state") == "paused":
			wait_for_power_state(client, server.atlas_vm_id, "start", "running")
		wait_for_power_state(client, server.atlas_vm_id, "stop", "stopped")

		try:
			client.resize(server.atlas_vm_id, cpu_millicores, memory_mib, disk_mib)
		except AtlasRejected:
			# Atlas kept the old shape. Restore the power state before reporting the refusal.
			if remote.get("current_state") != "stopped":
				wait_for_power_state(client, server.atlas_vm_id, "start", "running")
			raise
	elif disk_mib > (disk.get("size_mib") or 0):
		# A sleeping VM reports stopped while Atlas still wants it running. Wake it before the online grow.
		if remote.get("current_state") == "stopped" and remote.get("desired_state") == "running":
			wait_for_power_state(client, server.atlas_vm_id, "start", "running")

		client.update_disk(server.atlas_vm_id, disk_mib)

	wait_for_power_state(client, server.atlas_vm_id, "start", "running")
	observe_server(server)


def hold_server_stopped(server: VirtualMachine) -> None:
	"""Stop a server so that traffic does not wake it. Atlas refuses to stop a sleeping VM,
	and only an explicit stop keeps a VM down, so the server is started first. Safe to repeat."""
	client = get_client(server)
	wait_for_power_state(client, server.atlas_vm_id, "start", "running")
	wait_for_power_state(client, server.atlas_vm_id, "stop", "stopped")
	observe_server(server)


def convert_trial_server(server: str, start: bool) -> None:
	"""Background job: turn sleep off on a converted trial server, and start it when the
	trial had stopped it. Safe to repeat."""
	document = frappe.get_doc("Virtual Machine", server)
	client = get_client(document)
	client.set_compute_settings(document.atlas_vm_id, SLEEP_OFF_SETTINGS)
	if start:
		wait_for_power_state(client, document.atlas_vm_id, "start", "running")

	observe_server(document)


def wait_for_power_state(client: AtlasClient, vm_id: str, action: str, state: str) -> None:
	"""Wait until Atlas observes the VM in `state`, sending the power action once the VM is in
	a stable state. A `migrating` or `pending` VM is left to settle first — Atlas may be moving
	it to another host during a resize — and is never told to change power mid-transition."""
	deadline = time.monotonic() + POWER_WAIT_SECONDS
	acted = False
	while True:
		current = client.get_vm(vm_id).get("current_state")
		if current == state:
			return
		if not acted and current not in ("migrating", "pending"):
			client.vm_action(vm_id, action)
			acted = True
		if time.monotonic() > deadline:
			frappe.throw(
				_("The server did not reach the {0} state in time.").format(state), AtlasConnectionError
			)
		time.sleep(POWER_POLL_SECONDS)


def reconcile(team: str | None = None) -> dict:
	"""Enqueue a scoped read for each server Central owns, oldest report first. Never
	infer Team ownership from a regional list."""
	if team and not can_on_any_server(frappe.session.user, team, "server:view"):
		frappe.throw(_("You cannot refresh this Team's servers."), frappe.PermissionError)

	filters = {"status": ["!=", "Terminated"], "atlas_vm_id": ["is", "set"]}
	if team:
		filters["team"] = team

	servers = frappe.get_all(
		"Virtual Machine", filters=filters, pluck="name", limit=100, order_by="state_observed_at asc"
	)
	for name in servers:
		frappe.enqueue(
			"central.integrations.servers.refresh_server",
			name=name,
			enqueue_after_commit=True,
			job_id=f"server-refresh:{name}",
			deduplicate=True,
		)

	return {"synced": [], "stale": [], "queued": len(servers)}


def get_console_url(server: VirtualMachine, mode: ConsoleMode) -> str:
	"""Return a single-use Atlas web console URL for a running server.

	SSH opens a root shell with a key Atlas pushes for that session only. TTY opens the
	shared serial console, which every guest has and which asks for a user password."""
	server.require_server_access()
	if server.status != "Running":
		frappe.throw(_("Start the server before you open its console."))

	try:
		url = get_client(server).get_console_url(server.atlas_vm_id, mode=mode)
	except AtlasRejected:
		if mode != "ssh":
			raise
		frappe.throw(_("SSH did not start on this server. Open the serial console (TTY) instead."))

	ActivityEvent.record(server, f"server.{mode}_console_opened", CONSOLE)
	return url


def refresh_server(name: str) -> None:
	server = frappe.get_doc("Virtual Machine", name, for_update=True)
	if server.status != "Terminated":
		observe_server(server)


def get_client(server: VirtualMachine) -> AtlasClient:
	if not server.atlas_vm_id:
		frappe.throw(_("This server has no verified regional VM identity."))

	instance = frappe.get_cached_doc("Region", server.region)
	tenant_id = frappe.db.get_value("Team", server.team, "tenant_id")

	return AtlasClient(instance, tenant_id)


def update_firewall(server: VirtualMachine, change: FirewallChange) -> None:
	"""Change the firewall on Atlas, then read the result back."""
	get_client(server).update_network(server.atlas_vm_id, {"firewall": firewall.get_atlas_firewall(change)})
	observe_server(server)


def remove_legacy_device_rules() -> None:
	"""Remove the old rule that let every WireGuard VPN device pass the firewall, from every live
	server. Safe to run again: a server without the rule is left as it is."""
	servers = frappe.get_all(
		"Virtual Machine",
		filters={"status": ("!=", "Terminated"), "atlas_vm_id": ("is", "set")},
		pluck="name",
	)
	for name in servers:
		try:
			remove_legacy_device_rule(frappe.get_doc("Virtual Machine", name))
			frappe.db.commit()
		except Exception:
			# One unreachable region must not stop the rest. The log names the server to retry.
			frappe.db.rollback()
			frappe.log_error(
				title=f"WireGuard VPN firewall rule not removed: {name}",
				reference_doctype="Virtual Machine",
				reference_name=name,
			)


def remove_legacy_device_rule(server: VirtualMachine) -> None:
	"""Read the server's firewall from Atlas, then send it again without the old device rule."""
	if observe_server(server) == "Terminated":
		return

	rules = frappe.parse_json(frappe.db.get_value("Virtual Machine", server.name, "firewall_rules")) or {}
	inbound = rules.get("inbound") or []
	if firewall.LEGACY_DEVICE_RULE not in inbound:
		return

	kept = [rule for rule in inbound if rule != firewall.LEGACY_DEVICE_RULE]
	update_firewall(server, FirewallChange.model_validate({"inbound": kept}))


def set_public_ip(server: VirtualMachine, version: int, is_attached: bool) -> bool:
	"""Attach or detach the public IPv4 or IPv6 address, then wait briefly for Atlas to apply it.
	Returns False when the change is still in progress. A public IPv4 needs IPv4 internet access,
	so attaching one turns it on first."""
	client = get_client(server)
	if is_attached and version == 4 and not server.has_ipv4_internet:
		client.update_network(server.atlas_vm_id, {"ipv4_internet_access": True})

	if is_attached:
		client.attach_public_ip(server.atlas_vm_id, version)
	else:
		client.detach_public_ip(server.atlas_vm_id, version)

	is_done = wait_for_public_ip(client, server.atlas_vm_id, version, is_attached)
	observe_server(server)
	return is_done


def wait_for_public_ip(client: AtlasClient, vm_id: str, version: int, is_attached: bool) -> bool:
	deadline = time.monotonic() + ADDRESS_WAIT_SECONDS
	while time.monotonic() < deadline:
		network = client.get_vm(vm_id).get("network") or {}
		if bool(network.get(f"public_ipv{version}")) == is_attached:
			return True
		time.sleep(ADDRESS_POLL_SECONDS)

	return False


def set_ipv4_internet(server: VirtualMachine, enabled: bool) -> None:
	"""Turn IPv4 internet access on or off, then read the result back. Atlas keeps it on while
	the server has a public IPv4."""
	get_client(server).update_network(server.atlas_vm_id, {"ipv4_internet_access": enabled})
	observe_server(server)


def set_wireguard_access(server: VirtualMachine, enabled: bool) -> None:
	"""Let the team's WireGuard devices reach the server or cut them off, then read the result back."""
	get_client(server).update_network(server.atlas_vm_id, {"wireguard_gateway_access": enabled})
	observe_server(server)


def set_termination_protection(server: VirtualMachine, enabled: bool) -> bool:
	"""Change termination protection on Atlas and return the state Atlas reports."""
	remote = get_client(server).set_termination_protection(server.atlas_vm_id, enabled)
	if type(remote.get("is_termination_protected")) is not bool:
		raise AtlasConnectionError(_("Atlas returned an invalid termination protection state."))

	return remote["is_termination_protected"]


def get_cached_metrics(server: VirtualMachine, start: datetime, end: datetime | None = None) -> dict:
	"""The server's samples from `start` to `end` or now as its region measures them, cached for a minute."""
	key = f"atlas:metrics:{server.name}:{int(start.timestamp())}:{int(end.timestamp()) if end else 'now'}"
	if cached := frappe.cache.get_value(key):
		return cached

	try:
		payload = get_client(server).get_vm_metrics(server.atlas_vm_id, start, end)
		metrics = {
			"available": True,
			"points": get_metric_points(payload["samples"], server.vcpus),
			"sample_interval_seconds": payload["sample_interval_seconds"],
		}
	except AtlasConnectionError:
		# No frame locals: they hold the Atlas bearer token.
		frappe.log_error(title=f"Atlas metrics unavailable: {server.name}", message=frappe.get_traceback())
		metrics = {"available": False}

	frappe.cache.set_value(key, metrics, expires_in_sec=METRICS_CACHE_SECONDS)

	return metrics


def get_metric_points(samples: list[dict], vcpus: float) -> list[dict]:
	"""Atlas counts CPU time and network bytes from boot, so each point is the rate between
	two neighbouring samples. A pair that spans a down sample or a reboot has no rate."""
	return [
		get_metric_point(previous, sample, vcpus)
		for previous, sample in pairwise(samples)
		if sample["timestamp"] > previous["timestamp"]
	]


def get_metric_point(previous: dict, sample: dict, vcpus: float) -> dict:
	seconds = sample["timestamp"] - previous["timestamp"]
	is_up = previous["up"] and sample["up"]
	compute, disk = sample["compute"], sample["disk"]

	guest = sample.get("guest") or {}
	if guest.get("system_state", "unreachable") != "unreachable":
		# The guest's own view leaves out page cache that the host charges to the VM.
		memory, filesystem = guest["memory"], guest["root_filesystem"]
		memory_bytes = memory["total_bytes"] - memory["available_bytes"]
		disk_used_bytes, disk_total_bytes = filesystem["used_bytes"], filesystem["size_bytes"]
	else:
		memory_bytes = compute["memory_bytes"]
		disk_used_bytes, disk_total_bytes = disk["used_mib"] * MIB, disk["size_mib"] * MIB

	def rate(section: str, key: str) -> float | None:
		change = sample[section][key] - previous[section][key]
		return change / seconds if is_up and change >= 0 else None

	cpu_microseconds_per_second = rate("compute", "cpu_microseconds")

	return {
		"time": sample["timestamp"],
		"is_up": sample["up"],
		"cpu_percent": None
		if cpu_microseconds_per_second is None
		else min(100, cpu_microseconds_per_second / 10_000 / (vcpus or 1)),
		"memory_bytes": memory_bytes,
		"disk_used_bytes": disk_used_bytes,
		"disk_total_bytes": disk_total_bytes,
		"disk_read_bytes_per_second": disk["read_bytes_per_second"],
		"disk_write_bytes_per_second": disk["write_bytes_per_second"],
		"received_bytes_per_second": rate("network", "received_bytes"),
		"sent_bytes_per_second": rate("network", "sent_bytes"),
	}
