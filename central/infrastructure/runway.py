from datetime import UTC
import re
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, get_system_timezone, now_datetime

from central.iam import can, user_has_operator_bypass

OWNER_TTL_SECONDS = 60
TEAM_CONCURRENCY_LIMIT = 4


def authorize(pool) -> None:
	if user_has_operator_bypass():
		return
	if frappe.session.user != pool.controller_user or not all(
		can(frappe.session.user, pool.team, capability)
		for capability in ("server:view", "server:create", "server:terminate")
	):
		frappe.throw(_("This user cannot control the runner pool."), frappe.PermissionError)


def locked_pool(name: str):
	pool = frappe.get_doc("Runner Pool", name, for_update=True)
	authorize(pool)
	return pool


def check_fence(pool, owner_id: str, fence: int) -> None:
	if (
		pool.controller_owner != owner_id
		or int(pool.fence or 0) != int(fence)
		or not pool.owner_expires_at
		or get_datetime(pool.owner_expires_at) <= now_datetime()
	):
		frappe.throw(_("Runner controller ownership expired or changed."), frappe.PermissionError)


def save_internal(document) -> None:
	# Controller routes authorize the pool; service users cannot write lifecycle fields through Desk or REST.
	document.save(ignore_permissions=True)


def active_leases(pool: str | None = None, team: str | None = None, lock: bool = False) -> list:
	lease = frappe.qb.DocType("Runner Lease")
	query = (
		frappe.qb.from_(lease)
		.select(lease.name)
		.where((lease.phase != "deleted") | (lease.jit_state != "removed"))
		.orderby(lease.creation)
	)
	if pool:
		query = query.where(lease.pool == pool)
	if team:
		query = query.where(lease.team == team)
	if lock:
		query = query.for_update()
	return query.run(as_dict=True)


def leases_blocking_pool_change(pool: str, team: str) -> list:
	"""Return the leases whose runners could still be live against this pool's identity.

	The question a pool identity change has to answer is whether a runner might still be
	using the scale set, image or shape being replaced, not whether every lease's
	bookkeeping is finished. Those come apart when the controller is gone: it is the only
	party that can report a runner removed, so a lease whose VM has already disappeared
	keeps `jit_state: ready` for ever, and `active_leases` counts it as active.

	The reconciler cannot repair that on its own either, because it returns as soon as a
	lease is deleted. The result is a pool that can never be repointed again, and the only
	way out is a change to this code.

	So a lease blocks only while it could still have a runner on it: a VM that has not been
	confirmed absent, or a deadline that has not passed. Once the VM is gone the guest is
	destroyed and its JIT configuration is with it, whatever the lease still says, and the
	runner cannot be holding the old identity open.
	"""
	lease = frappe.qb.DocType("Runner Lease")
	return (
		frappe.qb.from_(lease)
		.select(lease.name)
		.where((lease.pool == pool) & (lease.team == team))
		# Unfinished bookkeeping, the same condition active_leases uses.
		.where((lease.phase != "deleted") | (lease.jit_state != "removed"))
		# And a runner that could still be on it. A confirmed absent VM is the stronger
		# evidence: the guest is destroyed and its JIT configuration went with it, whatever
		# the lease still says, so there is nothing left that could hold the old scale set,
		# image or shape open. vm_state is compared with an explicit null test because SQL
		# makes `NULL != 'absent'` unknown rather than true, and an unset state must count
		# as unknown rather than as absent.
		.where(
			lease.vm_state.isnull()
			| (lease.vm_state != "absent")
			| (lease.deadline > now_datetime())
		)
		.orderby(lease.creation)
		.run(as_dict=True)
	)


def iso_utc(value) -> str | None:
	if not value:
		return None
	return get_datetime(value).replace(tzinfo=ZoneInfo(get_system_timezone())).astimezone(UTC).isoformat()


def lease_snapshot(lease) -> dict:
	fields = (
		"pool",
		"team",
		"phase",
		"runner_name",
		"runner_id",
		"job_id",
		"repository",
		"request_labels",
		"workflow_run_id",
		"vm_id",
		"vm_state",
		"mesh_address",
		"last_error",
		"jit_state",
		"attempt_id",
		"acquire_state",
	)
	result = {field: lease.get(field) or (0 if field == "runner_id" else "") for field in fields}
	return {
		"id": lease.name,
		**result,
		"request_id": int(lease.request_id or 0),
		"deadline": iso_utc(lease.deadline),
	}


def pool_snapshot(pool) -> dict:
	fields = ("team", "region", "repository_url", "scale_set_id", "max_concurrency", "max_job_seconds")
	return {
		"fence": int(pool.fence),
		"pool": {
			"id": pool.name,
			**{field: pool.get(field) for field in fields},
			"enabled": pool.status == "Active",
			"owner_expires_at": iso_utc(pool.owner_expires_at),
		},
		"leases": [
			lease_snapshot(frappe.get_doc("Runner Lease", row.name))
			for row in active_leases(pool=pool.name, team=pool.team)
		],
	}


def claim_pool(pool: str, owner_id: str) -> dict:
	if not owner_id or len(owner_id) > 128:
		frappe.throw(_("Supply a controller instance identity."))
	document = locked_pool(pool)
	if (
		document.controller_owner
		and document.controller_owner != owner_id
		and document.owner_expires_at
		and get_datetime(document.owner_expires_at) > now_datetime()
	):
		frappe.throw(_("Another runner controller owns this pool."))
	document.controller_owner = owner_id
	document.fence = int(document.fence or 0) + 1
	document.owner_expires_at = add_to_date(now_datetime(), seconds=OWNER_TTL_SECONDS)
	save_internal(document)
	return pool_snapshot(document)


def renew_pool(pool: str, owner_id: str, fence: int, last_error: str = "") -> dict:
	document = locked_pool(pool)
	check_fence(document, owner_id, fence)
	document.owner_expires_at = add_to_date(now_datetime(), seconds=OWNER_TTL_SECONDS)
	document.last_error = str(last_error)[:1000]
	save_internal(document)
	return pool_snapshot(document)


def reserve_lease(pool: str, owner_id: str, fence: int, lease_id: str) -> dict:
	# Admission is database-only and keyed by the caller's UUID. Retrying a rolled-back
	# snapshot conflict cannot repeat an Atlas or GitHub mutation.
	for attempt in range(3):
		try:
			return _reserve_lease(pool, owner_id, fence, lease_id)
		except frappe.QueryDeadlockError:
			frappe.db.rollback()
			if attempt == 2:
				raise


def _reserve_lease(pool: str, owner_id: str, fence: int, lease_id: str) -> dict:
	try:
		identity = str(UUID(lease_id))
	except (ValueError, TypeError, AttributeError):
		frappe.throw(_("Runner lease identity must be a UUID."))
	team = frappe.db.get_value("Runner Pool", pool, "team")
	# Serialize aggregate team admission before pool admission, in one lock order.
	frappe.get_doc("Team", team, for_update=True)
	document = locked_pool(pool)
	check_fence(document, owner_id, fence)
	if frappe.db.exists("Runner Lease", identity):
		lease = scoped_lease(document, identity)
		return lease_snapshot(lease)
	if document.status != "Active":
		frappe.throw(_("The runner pool is paused."))
	if (
		len(active_leases(pool=pool, team=team, lock=True)) >= int(document.max_concurrency)
		or len(active_leases(team=team, lock=True)) >= TEAM_CONCURRENCY_LIMIT
	):
		frappe.throw(_("Runner capacity is exhausted."))
	lease = frappe.get_doc(
		{
			"doctype": "Runner Lease",
			"name": identity,
			"pool": pool,
			"team": team,
			"phase": "reserved",
			"attempt_id": identity,
			"fence": int(fence),
			"runner_name": f"runway-{UUID(identity).hex}",
			"jit_state": "none",
			"acquire_state": "none",
			"deadline": add_to_date(now_datetime(), seconds=int(document.max_job_seconds)),
		}
	)
	# The authenticated pool controller owns the reserved identity and capacity.
	lease.insert(ignore_permissions=True, set_name=identity)
	return lease_snapshot(lease)


# A label that carries a machine shape, like runway-4vcpu-8gb. The label is the only
# thing a repository writes, so it has to state the whole machine: whole vCPUs and whole
# GiB. Anything that does not parse is left to the pool, which is how a pool created before
# labels keeps working.
LABEL_SHAPE_PATTERN = re.compile(r"^runway-(\d+)vcpu-(\d+)gb$")
# A label beginning runway- followed by a digit has claimed to be a shape. One that fails
# to parse did not mean to name no shape, so it is a mistake and gets reported.
LABEL_SHAPE_CLAIM = re.compile(r"^runway-\d")


def resolve_shape(request_labels, pool):
	"""The machine a job with these labels gets, as (cpu_millicores, memory_mib, disk_mib).

	A scale set's runners are homogeneous, so a pool is one machine class. That makes a
	shape label a guard rather than a scheduler: it either names exactly the machine this
	pool serves, or names no shape at all and takes the pool's own. It cannot quietly ask
	for a different one, because a job written against the wrong label would then run on a
	machine it was never admitted to, which is the same silent mismatch as a bench restored
	into the wrong workspace.

	So three outcomes, and only the middle one is a guess:

	- runway-4vcpu-8gb on a pool serving exactly that: accepted.
	- self-hosted, runway-dogfood, or no shape: the pool's own machine.
	- anything else that claimed to be a shape: refused, naming the pool's shape, so the
	  job never runs on a machine different from the one its label asked for.
	"""
	labels = (request_labels or "").split()
	for label in labels:
		label = label.strip().lower()
		match = LABEL_SHAPE_PATTERN.match(label)
		if match:
			want = (int(match.group(1)) * 1000, int(match.group(2)) * 1024)
			serves = (int(pool.cpu_millicores or 0), int(pool.memory_mib or 0))
			if want == serves:
				return serves[0], serves[1], int(pool.disk_mib or 0)
			frappe.throw(
				_("Label {0} asks for {1} vCPU and {2} GiB, but this pool serves {3} vCPU and {4} GiB.").format(
					label,
					want[0] // 1000,
					want[1] // 1024,
					serves[0] // 1000,
					serves[1] // 1024,
				),
				frappe.ValidationError,
			)
		if LABEL_SHAPE_CLAIM.match(label):
			frappe.throw(
				_("Label {0} is not a runner shape. Use runway-<vcpu>vcpu-<memory>gb, such as runway-4vcpu-8gb.").format(
					label
				),
				frappe.ValidationError,
			)
	return int(pool.cpu_millicores or 0), int(pool.memory_mib or 0), int(pool.disk_mib or 0)


def pool_repository(pool) -> str:
	"""The owner/name this pool serves, derived from the repository it declares.

	The pool already declares a GitHub repository URL, validated to owner/name form and
	immutable while leases exist. That declaration is what a job is checked against, so the
	pairing decision stays inside Central rather than reaching into Atlas for the image
	record on every acquisition.
	"""
	url = urlsplit(pool.repository_url or "")
	path = url.path.strip("/").split("/")
	if len(path) != 2:
		return ""
	return f"{path[0]}/{path[1]}"


def ensure_image_serves(pool, repository: str) -> None:
	"""Refuse a pool that cannot serve this repository, before a guest exists.

	The pool declares the repository it serves. A job from anywhere else is refused here,
	where refusing is free, rather than after a VM boots and the job fails with a message
	about bench. The image record's own workspace declaration remains the bake-time source
	of truth; this is the selection-time check that the pool and the job agree.
	"""
	want = (repository or "").strip().lower()
	if not want:
		return
	serves = pool_repository(pool).lower()
	if not serves:
		return
	if serves == want:
		return
	frappe.throw(
		_("Runner pool {0} serves {1} and cannot serve {2}.").format(
			pool.name, pool_repository(pool), repository
		),
		frappe.PermissionError,
	)


def scoped_lease(pool, lease_id: str):
	lease = frappe.get_doc("Runner Lease", lease_id, for_update=True)
	if lease.pool != pool.name or lease.team != pool.team:
		frappe.throw(_("Runner lease belongs to another pool."), frappe.PermissionError)
	return lease


def fenced_lease(pool: str, owner_id: str, fence: int, lease_id: str):
	document = locked_pool(pool)
	check_fence(document, owner_id, fence)
	return document, scoped_lease(document, lease_id)


def update_lease(
	pool: str,
	owner_id: str,
	fence: int,
	lease_id: str,
	event: str,
	runner_id: int = 0,
	job_id: str = "",
	workflow_run_id: str = "",
	result: str = "",
	error: str = "",
	request_id: int = 0,
	repository: str = "",
	request_labels: str = "",
) -> dict:
	_, lease = fenced_lease(pool, owner_id, fence, lease_id)
	if event == "acquire_requested":
		if not 0 < int(request_id) < 2**63 or (lease.request_id and int(lease.request_id) != int(request_id)):
			frappe.throw(_("Job acquisition identity must remain a positive request ID."))
		if lease.phase in ("deleting", "deleted"):
			frappe.throw(_("A retiring runner cannot acquire work."))
		lease.request_id = str(request_id)
		# The repository is recorded here, before a guest exists, because that is the only
		# point at which refusing is still free. A pool whose image is baked for another
		# repository cannot serve this job, and finding that out after the VM is created
		# costs a boot and a failing job rather than a message.
		if repository:
			lease.repository = repository
			ensure_image_serves(frappe.get_doc("Runner Pool", pool), repository)
		if request_labels:
			lease.request_labels = str(request_labels)[:1000]
		# The shape is resolved and recorded here, alongside the repository, because this
		# is the last point at which the decision is still free. create_vm reads it back
		# rather than re-deriving it, so a label changed mid-flight cannot move a job onto
		# a machine it was not admitted to.
		cpu, memory, disk = resolve_shape(
			lease.request_labels, frappe.get_doc("Runner Pool", pool)
		)
		lease.resolved_cpu_millicores, lease.resolved_memory_mib, lease.resolved_disk_mib = (
			cpu, memory, disk,
		)
		lease.acquire_state = "pending" if lease.acquire_state != "acquired" else "acquired"
	elif event == "acquired":
		if not lease.request_id or lease.acquire_state not in ("pending", "acquired"):
			frappe.throw(_("Persist job acquisition intent first."))
		lease.acquire_state = "acquired"
	elif event == "runner_removed":
		lease.jit_state = "removed"
	elif event in ("completed", "failed"):
		if lease.phase != "deleted":
			lease.phase = "deleting"
		lease.result = str(result)[:140]
		lease.completed_at = now_datetime()
	else:
		transitions = {
			"jit_requested": ("vm_ready", "jit_pending"),
			"jit_ready": ("jit_pending", "jit_ready"),
			"bootstrapped": ("jit_ready", "running"),
			"started": ("running", "running"),
		}
		if event not in transitions:
			frappe.throw(_("Unknown runner lease event."))
		before, after = transitions[event]
		if lease.phase not in (before, after):
			frappe.throw(_("Runner lease event is invalid for its phase."))
		lease.phase = after
		if event in ("jit_requested", "jit_ready"):
			lease.jit_state = "pending" if event == "jit_requested" else "ready"
		if event in ("started", "bootstrapped"):
			lease.started_at = lease.started_at or now_datetime()
	for field, value in (("runner_id", runner_id), ("job_id", job_id), ("workflow_run_id", workflow_run_id)):
		if value:
			if lease.get(field) and str(lease.get(field)) != str(value):
				frappe.throw(_("Runner job identity changed within a lease."))
			lease.set(field, value)
	# The lease is a durable audit record. An event that carries no new error must keep the
	# recorded retirement reason or the failure to collect job diagnostics.
	if error:
		lease.last_error = str(error)[:1000]
	save_internal(lease)
	return lease_snapshot(lease)
