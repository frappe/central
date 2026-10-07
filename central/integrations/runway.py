import frappe
from frappe.utils import get_datetime, now_datetime

from central.errors import AtlasConnectionError, AtlasRejected, AtlasRequestUncertain, AtlasResourceGone
from central.infrastructure.runway import active_leases, fenced_lease, lease_snapshot, save_internal
from central.integrations.atlas import AtlasClient


def client_for_pool(pool) -> AtlasClient:
	return AtlasClient.for_team(frappe.get_doc("Region", pool.region), pool.team, capability="server:create")


def ensure_vm(pool: str, owner_id: str, fence: int, lease_id: str) -> dict:
	document, lease = fenced_lease(pool, owner_id, fence, lease_id)
	if (
		lease.phase == "reserved"
		and get_datetime(lease.deadline) > now_datetime()
		and document.status == "Active"
	):
		lease.phase = "provisioning"
		lease.create_dispatched_at = now_datetime()
		save_internal(lease)
		# Persist one dispatch intent before sending. An interrupted dispatch is never sent again.
		frappe.db.commit()
		create_vm(document, lease)
	else:
		frappe.db.commit()
	reconcile_lease(document, lease.name)
	return lease_snapshot(frappe.get_doc("Runner Lease", lease.name))


def create_vm(pool, lease) -> None:
	# The shape comes from the lease when acquisition recorded one, and from the pool
	# otherwise. A lease predating labels carries no resolved shape, so those keep booting
	# exactly what they always did.
	payload = {
		"image_id": pool.image_id,
		"cpu_millicores": int(lease.resolved_cpu_millicores or pool.cpu_millicores),
		"memory_mib": int(lease.resolved_memory_mib or pool.memory_mib),
		"disk_mib": int(lease.resolved_disk_mib or pool.disk_mib),
		"hostname": lease.runner_name,
		"ssh_keys": [pool.ssh_public_key],
		"sleep_after_idle_seconds": 0,
		"tags": {"runway_pool": pool.name, "runway_lease": lease.name, "role": "ci", "team": pool.team},
	}
	try:
		response = client_for_pool(pool).create_vm(payload)
	except AtlasRejected:
		lease.reload()
		lease.phase = "deleting"
		lease.create_dispatched_at = None
		lease.last_error = "Atlas rejected VM creation."
	except (AtlasRequestUncertain, AtlasConnectionError):
		lease.reload()
		lease.phase = "uncertain" if lease.phase not in ("deleting", "deleted") else lease.phase
		lease.last_error = "VM creation outcome is uncertain; reconciling tags without another create."
	else:
		lease.reload()
		if not response.get("id"):
			lease.phase = "uncertain" if lease.phase not in ("deleting", "deleted") else lease.phase
			lease.last_error = "Atlas create response did not identify a VM."
		else:
			lease.vm_id = response["id"]
	save_internal(lease)
	frappe.db.commit()


def pool_vms(pool) -> list[dict]:
	client = client_for_pool(pool)
	rows = []
	offset = 0
	while True:
		page = client.list_vms(limit=100, offset=offset)
		rows.extend(vm for vm in page if vm.get("tags", {}).get("runway_pool") == pool.name)
		if len(page) < 100:
			return rows
		offset += 100


def find_vm(pool, lease) -> str | None:
	matches = [vm for vm in pool_vms(pool) if vm.get("tags", {}).get("runway_lease") == lease.name]
	if len(matches) == 1:
		return matches[0]["id"]
	if len(matches) > 1:
		lease.last_error = "Multiple VMs match the lease; operator review is required."
	return None


def mark_deleted(lease) -> None:
	lease.phase = "deleted"
	lease.deleted_at = now_datetime()
	lease.vm_state = "absent"
	if lease.jit_state == "none":
		lease.jit_state = "removed"


def reconcile_lease(pool, name: str) -> None:
	# Take the pool row lock before the lease row lock, matching fenced_lease.
	# A reaper that locked the lease first would hold it across Atlas calls and
	# deadlock every controller RPC that already owns the pool lock.
	pool = frappe.get_doc("Runner Pool", pool.name, for_update=True)
	lease = frappe.get_doc("Runner Lease", name, for_update=True)
	if lease.phase == "deleted":
		frappe.db.commit()
		return
	if get_datetime(lease.deadline) <= now_datetime():
		lease.phase = "deleting"
	if not lease.vm_id and lease.create_dispatched_at:
		lease.vm_id = find_vm(pool, lease)
	if not lease.vm_id:
		if lease.phase == "deleting" and not lease.create_dispatched_at:
			mark_deleted(lease)
		save_internal(lease)
		frappe.db.commit()
		return
	client = client_for_pool(pool)
	try:
		state = client.get_vm(lease.vm_id)
	except AtlasResourceGone:
		mark_deleted(lease)
	else:
		lease.vm_state = state.get("current_state") or "unknown"
		lease.mesh_address = (state.get("network") or {}).get("mesh_ipv6") or ""
		if lease.phase == "deleting":
			lease.delete_requested_at = lease.delete_requested_at or now_datetime()
			save_internal(lease)
			frappe.db.commit()
			try:
				client.vm_action(lease.vm_id, "terminate")
			except AtlasResourceGone:
				# Confirm through GET on the next pass, rather than infer completion from DELETE.
				pass
			except AtlasRequestUncertain:
				lease.reload()
				lease.last_error = "VM deletion outcome is uncertain; waiting for scoped absence."
				save_internal(lease)
				frappe.db.commit()
			return
		elif lease.phase in ("provisioning", "uncertain") and lease.vm_state == "running":
			lease.phase = "vm_ready"
	save_internal(lease)
	frappe.db.commit()


def request_delete(pool: str, owner_id: str, fence: int, lease_id: str) -> dict:
	document, lease = fenced_lease(pool, owner_id, fence, lease_id)
	if lease.phase != "deleted":
		lease.phase = "deleting"
		save_internal(lease)
	frappe.db.commit()
	reconcile_lease(document, lease.name)
	return lease_snapshot(frappe.get_doc("Runner Lease", lease.name))


def sweep() -> None:
	# A system task repairs only VMs bearing an existing pool and lease identity.
	for row in frappe.get_all("Runner Pool", fields=["name", "team"]):
		pool = frappe.get_doc("Runner Pool", row.name)
		for lease in active_leases(pool=pool.name, team=pool.team):
			# End the read view opened by the enumeration above. reconcile_lease
			# locks the pool row, and a controller renewal that commits in between
			# would fail this transaction with "record has changed since last read".
			frappe.db.commit()
			try:
				reconcile_lease(pool, lease.name)
			except AtlasConnectionError:
				frappe.db.rollback()
				frappe.db.set_value(
					"Runner Lease",
					lease.name,
					"last_error",
					"Regional reconciliation failed; cleanup remains pending.",
				)
				frappe.db.commit()
		try:
			remove_orphans(pool)
		except AtlasConnectionError:
			frappe.db.rollback()
			frappe.db.set_value("Runner Pool", pool.name, "last_error", "Regional orphan scan failed.")
			frappe.db.commit()


def remove_orphans(pool) -> None:
	client = client_for_pool(pool)
	for vm in pool_vms(pool):
		tags = vm.get("tags") or {}
		identity = tags.get("runway_lease")
		if not identity or tags.get("team") != pool.team or tags.get("role") != "ci":
			continue
		if frappe.db.exists("Runner Lease", {"name": identity, "pool": pool.name, "team": pool.team}):
			continue
		try:
			client.vm_action(vm["id"], "terminate")
		except (AtlasResourceGone, AtlasRequestUncertain):
			pass
