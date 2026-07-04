# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Subscription intent + the two-axis state model (issue #04).

A Central Subscription is the customer's *intent/contract*. Agentless (ADR 0006):
Central provisions via the cluster manager and writes the authoritative runtime
record (the price-lock) itself, at provision time — see `provision_subscription`.
State lives on two orthogonal axes, never one enum:

  - operational (running / stopped / terminated) — Central's record of cluster-
    manager state (read from / reported by the cluster manager)
  - account standing (current / past_due / suspended) — owned by Central, here

Central never collapses the axes: a resource can be `running` and `past_due` at
once (normal grace), so one enum would lose information. Every standing transition
writes an append-only Subscription Change.
"""

import frappe


class InvalidTransition(frappe.ValidationError):
	"""An account-standing transition that the state machine does not permit."""


# Account-standing transitions Central allows. Suspension is staged through
# past_due (grace) — never a direct current -> suspended jump; reactivation
# returns to current from either past_due or suspended.
_STANDING_TRANSITIONS = {
	"Current": {"Past Due"},
	"Past Due": {"Current", "Suspended"},
	"Suspended": {"Current"},
}

# The Subscription Change type that records a move *into* a standing.
_STANDING_CHANGE_TYPE = {
	"Past Due": "Past Due",
	"Suspended": "Suspended",
	"Current": "Reactivated",
}


def _record_change(subscription: str, change_type: str, old_value=None, new_value=None, changed_by=None):
	"""Append one immutable Subscription Change row."""
	return frappe.get_doc(
		{
			"doctype": "Subscription Change",
			"subscription": subscription,
			"change_type": change_type,
			"old_value": old_value,
			"new_value": new_value,
			"effective_at": frappe.utils.now_datetime(),
			"changed_by": changed_by or frappe.session.user,
		}
	).insert(ignore_permissions=True)


def create_subscription(
	team: str,
	cluster: str,
	plan: str | None = None,
	billing_cycle: str = "Monthly",
	start_date=None,
	default_payment_method: str | None = None,
	gateway: str | None = None,
	changed_by: str | None = None,
	resource_id: str | None = None,
	pricing_mode: str = "Preset",
	includes: list | None = None,
	sub_category: str | None = None,
):
	"""Record a subscription INTENT — what the customer asked for — linked to its
	runtime Asset. The Asset is the resource Central drives on a cluster (it carries
	the region); the Subscription is the billing contract that links to it via
	`asset_id`. Billing resolves the region (and so the rate snapshot) through the
	Asset (ADR 0006, cdea38e). The actual provisioning (calling the cluster manager
	and writing the price-lock) is `provision_subscription`; this captures the
	contract + its asset only, so it stays usable for fixtures and intent-only flows.

	A `Composed` subscription mints no Plan: it carries `includes` (qty per Resource
	Type) as its locked composition and `sub_category` as its optimisation profile;
	billing reads the summed config rate off its Subscription Change (ADR 0009/0010).

	The cluster must be a registered Atlas Instance (Asset.cluster is a reqd Link)."""
	resource_id = resource_id or f"vm-{frappe.generate_hash(length=10)}"
	if not frappe.db.exists("Asset", resource_id):
		# Pending — not Running — so the Asset status-sync does not race us to create
		# a second Subscription for this asset.
		frappe.get_doc(
			{
				"doctype": "Asset",
				"resource_id": resource_id,
				"team": team,
				"cluster": cluster,
				"plan": plan,
				"status": "Pending",
				**_asset_shape(includes),
			}
		).insert(ignore_permissions=True)

	doc = frappe.get_doc(
		{
			"doctype": "Subscription",
			"team": team,
			"asset_id": resource_id,
			"pricing_mode": pricing_mode,
			"plan": plan,
			"sub_category": sub_category,
			"includes": includes or [],
			"billing_cycle": billing_cycle,
			"account_standing": "Current",
			"start_date": start_date or frappe.utils.nowdate(),
			"default_payment_method": default_payment_method,
			"gateway": gateway,
		}
	)
	doc.flags.changed_by = changed_by
	doc.insert(ignore_permissions=True)

	return doc


def _asset_shape(includes) -> dict:
	"""Record a composed config's real shape on its Asset so the running machine
	reflects what was provisioned. Empty for a preset (the Plan carries the shape)."""
	if not includes:
		return {}
	from central.billing.catalog.composition import composition_quantities, COMPUTE, MEMORY, DISK

	qty = composition_quantities(includes)
	return {
		"vcpus": int(qty.get(COMPUTE, 0)),
		"memory_megabytes": int(qty.get(MEMORY, 0) * 1024),
		"disk_gigabytes": int(qty.get(DISK, 0)),
	}


def provision_composed_subscription(
	team: str,
	cluster: str,
	includes: list,
	sub_category: str,
	billing_cycle: str = "Monthly",
	start_date=None,
	resource_id: str | None = None,
	default_payment_method: str | None = None,
	gateway: str | None = None,
	changed_by: str | None = None,
):
	"""Provision a design-your-own compute config (ADR 0009, #80). No Plan is minted.

	The shape is validated against its optimisation profile (#81), then Central writes
	the composition onto the Subscription and stamps the summed whole-config rate on
	the opening `Created` Subscription Change (done in the controller's after_insert).
	Grandfathering holds while the config is unchanged — a later rate-card edit does
	not re-price a running config; only a resize re-resolves (#82).
	"""
	from central.billing.catalog.composition import validate_composition
	from central.billing.catalog.pricing import resolve_config_rate

	validate_composition(sub_category, includes)
	# Re-check the config fits the team's remaining headroom (#83) — the client bounds
	# are a convenience, the server is the gate.
	currency = frappe.db.get_value("Billing Profile", team, "currency")
	enforce_headroom(team, resolve_config_rate(includes, currency, cluster))
	resource_id = resource_id or f"res-{frappe.generate_hash(length=10)}"
	sub = create_subscription(
		team, cluster, plan=None, billing_cycle=billing_cycle, start_date=start_date,
		default_payment_method=default_payment_method, gateway=gateway, changed_by=changed_by,
		resource_id=resource_id, pricing_mode="Composed", includes=includes, sub_category=sub_category,
	)
	opening = frappe.db.get_value(
		"Subscription Change",
		{"subscription": sub.name, "change_type": "Created"},
		["locked_rate", "currency"],
		as_dict=True,
	)
	return {
		"subscription": sub.name,
		"resource_id": resource_id,
		"locked_rate": opening.locked_rate if opening else None,
		"currency": opening.currency if opening else None,
	}


def provision_subscription(
	team: str,
	cluster: str,
	plan: str,
	billing_cycle: str = "Monthly",
	start_date=None,
	resource_id: str | None = None,
	default_payment_method: str | None = None,
	gateway: str | None = None,
	changed_by: str | None = None,
):
	"""Provision a subscription the agentless way (ADR 0006): record the intent, which
	— as the *same* component — opens the authoritative billing segment.

	Central calls the cluster manager to create the resource (here the seam mints a
	`resource_id`; a real impl uses the id the cluster manager returns). Creating the
	Subscription opens its `Created` Subscription Change at the catalog rate for the
	team's currency + cluster — that segment IS the price-lock (ADR 0010), so the rate
	shown is the rate locked, with no separate ledger to keep in sync. Returns the
	subscription + the locked handles."""
	resource_id = resource_id or f"res-{frappe.generate_hash(length=10)}"
	sub = create_subscription(
		team, cluster, plan, billing_cycle=billing_cycle, start_date=start_date,
		default_payment_method=default_payment_method, gateway=gateway, changed_by=changed_by,
		resource_id=resource_id,
	)

	opening = frappe.db.get_value(
		"Subscription Change",
		{"subscription": sub.name, "change_type": "Created"},
		["locked_rate", "currency"],
		as_dict=True,
	)
	return {
		"subscription": sub.name,
		"resource_id": resource_id,
		"shown_rate": opening.locked_rate if opening else None,
		"currency": opening.currency if opening else None,
	}


def provision_service_subscription(
	team: str,
	plan: str,
	cluster: str | None = None,
	billing_cycle: str = "Monthly",
	start_date=None,
	default_payment_method: str | None = None,
	gateway: str | None = None,
	changed_by: str | None = None,
):
	"""Subscribe a team to a team-level metered service (ADR 0013/0015).

	Unlike a VM subscription, this mints no Asset and calls no cluster manager: it
	synthesizes a virtual subject per `(team, plan, cluster)`, records the intent, and
	opens the authoritative billing segment (the `Created` Subscription Change — the
	price-lock itself, ADR 0010) inline. A service subject is always alive while
	subscribed; there is no stop/start.

	Idempotent: re-subscribing the same team to the same service on the same cluster
	returns the existing subscription rather than opening a parallel subject. Returns
	the subscription + the synthesized subject + the locked handles."""
	_assert_service_plan(plan)

	subject = _service_subject_id(team, plan, cluster)
	existing = frappe.db.get_value(
		"Subscription", {"service_subject": subject, "enabled": 1}, "name"
	)
	if existing:
		seg = _latest_segment_by_subscription([existing]).get(existing)
		return {
			"subscription": existing,
			"service_subject": subject,
			"reused": True,
			"locked_rate": frappe.utils.flt(seg.locked_rate) if seg else None,
			"currency": seg.currency if seg else None,
		}

	doc = frappe.get_doc(
		{
			"doctype": "Subscription",
			"team": team,
			"service_subject": subject,
			"cluster": cluster,
			"pricing_mode": "Preset",
			"plan": plan,
			"billing_cycle": billing_cycle,
			"account_standing": "Current",
			"enabled": 1,
			"start_date": start_date or frappe.utils.nowdate(),
			"default_payment_method": default_payment_method,
			"gateway": gateway,
		}
	)
	doc.flags.changed_by = changed_by
	doc.insert(ignore_permissions=True)

	opening = frappe.db.get_value(
		"Subscription Change",
		{"subscription": doc.name, "change_type": "Created"},
		["locked_rate", "currency"],
		as_dict=True,
	)
	return {
		"subscription": doc.name,
		"service_subject": subject,
		"reused": False,
		"locked_rate": opening.locked_rate if opening else None,
		"currency": opening.currency if opening else None,
	}


def _assert_service_plan(plan: str) -> None:
	"""A team-level service plan is any active Plan whose family is not provisioned as a
	whole Server (servers go through the VM create/resize flow, ADR 0007). Metered
	families (AI Tokens, PDF, storage) and non-Server bundles qualify."""
	category = frappe.db.get_value("Plan", plan, "category")
	if not category:
		frappe.throw(frappe._("Unknown plan {0}.").format(plan), frappe.ValidationError)
	if frappe.db.get_value("Plan Category", category, "provision_target") == "Server":
		frappe.throw(
			frappe._("Plan {0} provisions a server — subscribe it through the server flow, not as a team-level service.").format(plan),
			frappe.ValidationError,
		)


def _service_subject_id(team: str, plan: str, cluster: str | None) -> str:
	"""A deterministic, collision-safe virtual subject per (team, service-plan, cluster),
	so re-subscribing the same service resolves to the same subject (idempotency)."""
	import hashlib

	seed = f"{team}|{plan}|{cluster or ''}"
	return "svc-" + hashlib.sha1(seed.encode()).hexdigest()[:16]


def change_plan(subscription: str, new_plan: str, changed_by: str | None = None):
	"""Switch a subscription onto a curated preset (intent). The controller opens the
	new billing segment on save (the `changed`-event re-lock, ADR 0010) — this just
	mutates the contract. Switching a composed config onto a preset drops the
	composition (and so the à-la-carte pricing); picking the same preset is a no-op."""
	doc = frappe.get_doc("Subscription", subscription)
	if doc.pricing_mode != "Composed" and new_plan == doc.plan:
		return doc
	doc.pricing_mode = "Preset"
	doc.plan = new_plan
	doc.sub_category = None
	doc.set("includes", [])
	doc.flags.changed_by = changed_by
	doc.save(ignore_permissions=True)
	return doc


def begin_resize(
	subscription: str,
	*,
	plan: str | None = None,
	includes: list | None = None,
	sub_category: str | None = None,
	changed_by: str | None = None,
) -> dict:
	"""Console's resize front door (#84). A real Firecracker resize is slow — the host
	stops the VM, rewrites its machine config, grows the rootfs, and starts it again — so
	we never run it inline in the request. Instead:

	  1. validate synchronously, so the user still gets the common errors (disk shrink,
	     same-config no-op) immediately;
	  2. mark the VM `resize_in_progress` — the Console renders a live "Resizing" state
	     and blocks power actions off this flag (see central/api/servers.py);
	  3. hand the reshape + billing re-lock to a background job, and return at once.

	A resize with no live VM to reshape (never provisioned) has nothing slow to defer, so
	it re-locks inline. Returns `{queued, resized}`: `resized` is False only for a no-op
	or a non-resizable config."""
	doc = frappe.get_doc("Subscription", subscription)
	if not _is_resizable(doc):
		return {"queued": False, "resized": False}
	asset = (
		frappe.db.get_value("Asset", doc.asset_id, ["cluster", "status", "resize_in_progress"], as_dict=True)
		if doc.asset_id
		else None
	)
	if asset and asset.resize_in_progress:
		frappe.throw(frappe._("This server is already resizing — wait for it to finish."))

	shape = _plan_resize(doc, asset, plan, includes, sub_category)
	if shape is None:
		return {"queued": False, "resized": False}  # same config — nothing to do

	# No live VM to reshape → re-lock the contract inline (nothing slow to defer).
	if not asset or asset.status not in ("Running", "Paused", "Stopped"):
		_apply_resize(subscription, plan=plan, includes=includes, sub_category=sub_category, changed_by=changed_by)
		return {"queued": False, "resized": True}

	# Slow path: flag the VM Resizing (pushed live to the Console) and defer the reshape.
	from central.central.doctype.asset.asset import Asset

	Asset.mark_resizing(doc.asset_id, True)
	frappe.enqueue(
		_apply_resize,
		queue="long",
		timeout=600,
		enqueue_after_commit=True,
		subscription=subscription,
		plan=plan,
		includes=includes,
		sub_category=sub_category,
		changed_by=changed_by,
		asset_id=doc.asset_id,
	)
	return {"queued": True, "resized": True}


def _plan_resize(doc, asset, plan, includes, sub_category) -> dict | None:
	"""Decide a resize synchronously: return the target VM shape (vcpus/memory/disk), or
	None when it's a no-op (same config). Runs the VM-free checks — no-op detection,
	headroom, and the disk-shrink guard — so the user gets these errors immediately,
	before anything is queued; the worker re-runs them authoritatively when it applies
	the resize. (Composition validity is left to the worker.)"""
	currency = frappe.db.get_value("Billing Profile", doc.team, "currency")
	cluster = asset.cluster if asset else None
	if plan:
		if doc.pricing_mode == "Preset" and doc.plan == plan:
			return None
		shape = _plan_shape(plan)
		new_rate = frappe.get_doc("Plan", plan).get_rate(currency, cluster)
	else:
		from central.billing.catalog.composition import composition_quantities
		from central.billing.catalog.pricing import resolve_config_rate

		rows = [dict(r) for r in (includes or [])]
		if doc.pricing_mode == "Composed" and composition_quantities(doc.includes) == composition_quantities(rows):
			return None
		shape = _asset_shape(rows)
		new_rate = resolve_config_rate(rows, currency, cluster)
	enforce_headroom(doc.team, new_rate, exclude=doc.name)
	if asset and asset.status in ("Running", "Paused", "Stopped"):
		_guard_disk_shrink(doc.asset_id, shape)
	return shape


def _apply_resize(
	subscription: str,
	*,
	plan: str | None = None,
	includes: list | None = None,
	sub_category: str | None = None,
	changed_by: str | None = None,
	asset_id: str | None = None,
) -> None:
	"""Apply a resize through the existing synchronous functions — reshape the real VM
	(slow) then re-lock billing. Runs in a background job for a live VM (so the request
	returns fast), or inline when there's no VM to reshape. Always clears the Resizing
	flag: on failure it rolls back the partial billing write, then clears the flag on its
	own committed write so the Console can't wedge on a stuck "Resizing" state, and
	re-raises so the job is recorded as failed (billing stays on the old segment — we
	never re-price to a shape the host didn't apply)."""
	from central.central.doctype.asset.asset import Asset

	try:
		if plan:
			resize_to_plan(subscription, plan, changed_by=changed_by)
		else:
			resize_composed_subscription(subscription, includes or [], sub_category, changed_by=changed_by)
	except Exception:
		if asset_id:
			frappe.db.rollback()
			Asset.mark_resizing(asset_id, False)
			frappe.db.commit()
		raise
	if asset_id:
		Asset.mark_resizing(asset_id, False)


def resize_composed_subscription(
	subscription: str,
	includes: list,
	sub_category: str | None = None,
	changed_by: str | None = None,
):
	"""Resize a composed config — or slide a preset onto a custom shape — as the
	`changed`-event re-lock (#82, ADR 0010).

	Closes the open segment and opens a new one whose `locked_rate` is the config
	total **re-resolved at the current rate card**; grandfathering protects only the
	*unchanged* config. The new shape is validated against its profile (#81) and the
	team's remaining headroom before anything is written. A no-op on an identical
	composition (matching #54), and records nothing on a never-provisioned or
	terminated config.
	"""
	doc = frappe.get_doc("Subscription", subscription)
	if not _is_resizable(doc):
		return None

	profile = sub_category or doc.sub_category
	if not profile:
		frappe.throw(frappe._("A composed config needs an optimisation profile."))

	rows = [dict(r) for r in includes]
	from central.billing.catalog.composition import composition_quantities, validate_composition
	from central.billing.catalog.pricing import resolve_config_rate

	validate_composition(profile, rows)

	currency = frappe.db.get_value("Billing Profile", doc.team, "currency")
	asset = (
		frappe.db.get_value("Asset", doc.asset_id, ["cluster", "status"], as_dict=True)
		if doc.asset_id
		else None
	)
	new_rate = resolve_config_rate(rows, currency, asset.cluster if asset else None)
	enforce_headroom(doc.team, new_rate, exclude=subscription)

	# Resizing to the identical composition already running is a no-op (no event).
	if doc.pricing_mode == "Composed" and composition_quantities(doc.includes) == composition_quantities(rows):
		return doc

	if asset:
		# Reshape the real VM on its Atlas BEFORE re-pricing (the Atlas seam, #54): if
		# the host rejects the resize we must not open a new — mis-priced — billing
		# segment. Central's mirror picks up the new shape from the vm.resized event
		# Atlas emits, so we no longer write it here.
		_reshape_vm(doc.asset_id, asset.cluster, asset.status, _asset_shape(rows))

	doc.pricing_mode = "Composed"
	doc.plan = None
	doc.sub_category = profile
	doc.set("includes", rows)
	doc.flags.changed_by = changed_by
	doc.save(ignore_permissions=True)  # controller appends the Plan Changed re-lock
	return doc


def resize_to_plan(subscription: str, new_plan: str, changed_by: str | None = None):
	"""Resize a server onto a preset bundle: reshape the VM to the bundle's size,
	then switch the billing contract onto it. The counterpart to
	`resize_composed_subscription` for a preset target (#84), so the console's one
	Resize action covers bundles as well as custom shapes. A no-op when the server is
	already on this preset; records nothing on a never-provisioned/terminated config."""
	doc = frappe.get_doc("Subscription", subscription)
	if not _is_resizable(doc):
		return None
	if doc.pricing_mode == "Preset" and doc.plan == new_plan:
		return doc
	asset = (
		frappe.db.get_value("Asset", doc.asset_id, ["cluster", "status"], as_dict=True)
		if doc.asset_id
		else None
	)
	# Refuse a resize that would push the team past its trust-tier headroom — the same
	# gate resize_composed_subscription applies, so a preset target can't slip past the
	# spend cap. Authoritative here (covers every caller, incl. the background job);
	# begin_resize also checks it synchronously for immediate feedback.
	currency = frappe.db.get_value("Billing Profile", doc.team, "currency")
	new_rate = frappe.get_doc("Plan", new_plan).get_rate(currency, asset.cluster if asset else None)
	enforce_headroom(doc.team, new_rate, exclude=subscription)
	if asset:
		_reshape_vm(doc.asset_id, asset.cluster, asset.status, _plan_shape(new_plan))
	return change_plan(subscription, new_plan, changed_by=changed_by)


def _plan_shape(plan: str) -> dict:
	"""A preset Plan's bundled size as the _asset_shape dict (vcpus/memory/disk)."""
	includes = frappe.get_all(
		"Plan Includes",
		filters={"parenttype": "Plan", "parent": plan},
		fields=["resource_type", "quantity"],
	)
	return _asset_shape(includes)


def _guard_disk_shrink(asset_id: str, shape: dict) -> None:
	"""Refuse a resize that would shrink the disk — Atlas can only grow a rootfs. Cheap
	and VM-free, so `begin_resize` runs it synchronously to surface the error to the user
	before the slow reshape is ever queued (and `_reshape_vm` re-checks as a backstop)."""
	if not shape:
		return
	current_disk = frappe.utils.cint(frappe.db.get_value("Asset", asset_id, "disk_gigabytes"))
	if shape["disk_gigabytes"] < current_disk:
		frappe.throw(
			frappe._("Disk can't shrink: this server has a {0} GB disk — choose a size with at least that much storage.").format(current_disk)
		)


def _reshape_vm(asset_id: str, cluster: str, status: str, shape: dict) -> None:
	"""Apply `shape` (vcpus/memory/disk) to the real VM on its Atlas, stopping it first
	when it's live. Firecracker can't reconfigure a running machine, so a Running/Paused
	VM is stopped, then resized, then STARTED BACK UP — the stop→resize→start cycle
	returns the server to the running state the user found it in, so a resize doesn't
	silently leave it powered off. A VM that was already Stopped stays Stopped (resizing
	an off server doesn't power it on), and one that isn't provisioned yet (Pending/Failed)
	has nothing to reshape and is skipped.

	Two guards keep a failed resize from stranding the VM powered off: a disk shrink
	(which Atlas refuses — a rootfs can only grow) is caught HERE, before anything is
	stopped; and if the on-host resize fails for any other reason after we've stopped a
	live VM, we start it back up before re-raising. Atlas's stop/start/resize are
	synchronous, so each step has finished before the next runs — the VM is Running
	again by the time this returns, no background job in the loop."""
	if not shape or status not in ("Running", "Paused", "Stopped"):
		return
	_guard_disk_shrink(asset_id, shape)
	from central.integrations.atlas import AtlasClient

	client = AtlasClient(frappe.get_doc("Atlas Instance", cluster))
	was_active = status in ("Running", "Paused")
	if was_active:
		client.vm_action(asset_id, "stop")
	try:
		client.resize_vm(
			asset_id,
			vcpus=shape["vcpus"],
			memory_megabytes=shape["memory_megabytes"],
			disk_gigabytes=shape["disk_gigabytes"],
		)
	except Exception:
		# Reshape failed after we stopped a live VM — bring it back so a failed resize
		# doesn't leave it powered off, then surface the original error (a restart that
		# also fails is logged, not raised, so it can't mask the real cause).
		if was_active:
			try:
				client.vm_action(asset_id, "start")
			except Exception:
				frappe.log_error(title=f"Resize recovery: failed to restart {asset_id}")
		raise
	# Resize landed. A VM that was live before the resize is started back up so the
	# server comes back on its own — the whole stop→resize→start cycle is invisible to
	# the user. The resize itself has already succeeded (and billing will re-lock), so a
	# start that fails here is logged, not raised: worst case is a resized-but-stopped VM
	# the user can start manually, exactly the old behaviour — never a lost resize.
	if was_active:
		try:
			client.vm_action(asset_id, "start")
		except Exception:
			frappe.log_error(title=f"Resize: reshaped but failed to restart {asset_id}")


def _is_resizable(doc) -> bool:
	"""A config can be resized only while it is provisioned and live — not before its
	opening segment, after a cancellation, or once the machine is terminated."""
	latest = frappe.get_all(
		"Subscription Change",
		filters={"subscription": doc.name, "change_type": ["in", ["Created", "Plan Changed", "Cancelled"]]},
		pluck="change_type",
		order_by="effective_at desc, creation desc",
		limit=1,
	)
	if not latest or latest[0] == "Cancelled":
		return False
	if doc.asset_id and frappe.db.get_value("Asset", doc.asset_id, "status") == "Terminated":
		return False
	return True


# The Subscription Change types that bear a rate and bound a billing segment. A
# segment is "open" when the latest such change is Created/Plan Changed, not a
# terminal Cancelled.
_SEGMENT_CHANGE_TYPES = ["Created", "Plan Changed", "Cancelled"]


def _latest_segment_by_subscription(subscription_names: list[str]) -> dict:
	"""The most-recent rate-bearing change per subscription, in ONE batched query.

	Ordered newest-first so the first row seen per subscription is its latest segment
	marker; this replaces the per-subscription query that made `team_run_rate` an N+1
	on a hot read (review notes #2)."""
	if not subscription_names:
		return {}
	rows = frappe.get_all(
		"Subscription Change",
		filters={"subscription": ["in", subscription_names], "change_type": ["in", _SEGMENT_CHANGE_TYPES]},
		fields=["subscription", "change_type", "locked_rate", "currency"],
		order_by="effective_at desc, creation desc",
	)
	latest: dict = {}
	for r in rows:
		latest.setdefault(r.subscription, r)
	return latest


def _asset_clusters(asset_ids) -> dict:
	"""Map asset_id -> cluster in one query (cluster lives on the Asset, cdea38e)."""
	ids = [a for a in set(asset_ids) if a]
	if not ids:
		return {}
	return {
		r.name: r.cluster
		for r in frappe.get_all("Asset", filters={"name": ["in", ids]}, fields=["name", "cluster"])
	}


def active_segments(filters: dict | None = None) -> list:
	"""Every open, rate-bearing billing segment — one row per subscription — resolved
	from the `Subscription Change` ledger (ADR 0010) in batched queries.

	This is THE single source of truth for "what is a team running", replacing the
	retired `Price Lock` reads (#86). A preset and a composed subscription are treated
	identically, so a composed config is finally visible everywhere a preset is —
	"resources used", admin consumption, team-clusters, the currency fallback.

	`filters` narrows the underlying Subscriptions (e.g. `{"team": t}` or
	`{"plan": p}`). Each row is a `frappe._dict`: subscription, team, plan,
	pricing_mode, asset_id, resource_id, cluster, currency, locked_rate."""
	subs = frappe.get_all(
		"Subscription",
		filters=filters or {},
		fields=["name", "team", "plan", "pricing_mode", "asset_id", "service_subject", "cluster"],
	)
	if not subs:
		return []
	latest = _latest_segment_by_subscription([s.name for s in subs])
	clusters = _asset_clusters([s.asset_id for s in subs])
	out = []
	for s in subs:
		seg = latest.get(s.name)
		if not seg or seg.change_type == "Cancelled":
			continue
		# A VM subscription is subjected by its Asset (cluster off the Asset); a
		# team-level service subject has no Asset — its id and cluster live on the
		# Subscription itself (ADR 0013). Either way the resource_id keys metering.
		resource_id = s.asset_id or s.service_subject
		out.append(
			frappe._dict(
				{
					"subscription": s.name,
					"team": s.team,
					"plan": s.plan,
					"pricing_mode": s.pricing_mode,
					"asset_id": s.asset_id,
					"service_subject": s.service_subject,
					"resource_id": resource_id,
					"cluster": clusters.get(s.asset_id) or s.cluster,
					"currency": seg.currency,
					"locked_rate": frappe.utils.flt(seg.locked_rate),
				}
			)
		)
	return out


def team_active_segments(team: str) -> list:
	"""A team's open priced segments — see `active_segments`."""
	return active_segments({"team": team})


def active_segment_for_resource(resource_id: str):
	"""The open priced segment for a metered subject, or None. A VM resource is named
	by its Asset (`asset_id`); a team-level service subject is named by the synthesized
	`service_subject` (ADR 0013). Either maps to at most one subscription. Used by
	metering to grandfather a subject's terms off the ledger (#86)."""
	segs = active_segments({"asset_id": resource_id})
	if not segs:
		segs = active_segments({"service_subject": resource_id})
	return segs[0] if segs else None


def current_segment_rate(subscription: str) -> float:
	"""The locked_rate of a subscription's currently-open billing segment, or 0 when
	it is cancelled / never priced. The open segment is the latest Created/Plan Changed
	not closed by a later Cancelled (ADR 0010 — the ledger is the lock)."""
	seg = _latest_segment_by_subscription([subscription]).get(subscription)
	if not seg or seg.change_type == "Cancelled":
		return 0.0
	return frappe.utils.flt(seg.locked_rate)


def team_run_rate(team: str, exclude: str | None = None) -> float:
	"""The team's committed monthly run-rate: the summed open-segment locked rate of
	its subscriptions (preset and composed alike). A team bills in one currency, so the
	rates are already comparable. `exclude` drops one subscription — used by resize to
	measure headroom as if the config being resized weren't there. One batched query
	via `team_active_segments` (no per-subscription N+1, review notes #2)."""
	return frappe.utils.flt(
		sum(s.locked_rate for s in team_active_segments(team) if s.subscription != exclude)
	)


def enforce_headroom(team: str, new_rate, exclude: str | None = None) -> None:
	"""Reject a config that can't be priced, or that would push the team past its
	remaining trust-tier headroom (the spend cap minus its other running run-rate).
	The authoritative server-side gate reused by provision (#83) and resize (#82)."""
	from central.billing.catalog.entitlements import get_team_caps

	if new_rate is None:
		frappe.throw(frappe._("This configuration cannot be priced in your currency."))
	cap = frappe.utils.flt(get_team_caps(team).max_spend)
	available = max(0.0, cap - team_run_rate(team, exclude=exclude))
	if frappe.utils.flt(new_rate) > available:
		frappe.throw(
			frappe._("This configuration ({0}) exceeds your remaining headroom ({1}).").format(
				frappe.utils.flt(new_rate), frappe.utils.flt(available)
			)
		)


def change_payment_method(subscription: str, new_method: str, changed_by: str | None = None):
	doc = frappe.get_doc("Subscription", subscription)
	old_method = doc.default_payment_method
	doc.default_payment_method = new_method
	doc.save(ignore_permissions=True)
	_record_change(subscription, "Payment Method Changed", old_method, new_method, changed_by)
	return doc


def cancel_subscription(subscription: str, changed_by: str | None = None):
	"""Cancel the subscription intent. The contract record is kept; the
	cancellation is logged. Stopping/terminating the running resource is a separate
	operational step Central drives via the cluster manager (ADR 0006)."""
	_record_change(subscription, "Cancelled", changed_by=changed_by)
	return frappe.get_doc("Subscription", subscription)


def pause_billing(subscription: str, changed_by: str | None = None):
	"""Pause billing for a subscription. Disables the subscription, logs the change,
	and STOPS the linked server resource — the VM and the sites/services running on
	it — so a paused subscription is not left running and accruing. A no-op if
	already paused. If the server can't be stopped the whole pause rolls back."""
	doc = frappe.get_doc("Subscription", subscription)
	if not doc.enabled:
		return doc
	doc.enabled = 0
	doc.save(ignore_permissions=True)
	_record_change(subscription, "Paused", old_value=1, new_value=0, changed_by=changed_by)
	_control_subscription_server(doc, "stop")
	return doc


def resume_billing(subscription: str, changed_by: str | None = None):
	"""Resume billing for a paused subscription. Re-enables it, logs the change, and
	starts the linked server back up. A no-op if already active."""
	doc = frappe.get_doc("Subscription", subscription)
	if doc.enabled:
		return doc
	doc.enabled = 1
	doc.save(ignore_permissions=True)
	_record_change(subscription, "Resumed", old_value=0, new_value=1, changed_by=changed_by)
	_control_subscription_server(doc, "start")
	return doc


# States from which a stop / start is a meaningful Atlas transition; in any other
# state the action is a no-op we skip (avoids erroring on e.g. stopping a server
# that is already stopped, or one never provisioned).
_SERVER_ACTION_FROM = {"stop": {"Running"}, "start": {"Stopped", "Paused", "Failed"}}


def _control_subscription_server(sub, action: str) -> None:
	"""Drive the subscription's linked server through the very same operator methods
	the server listing uses — central.api.servers.stop_server / start_server — so
	pausing a subscription stops its VM and resuming starts it back. Skips when there
	is no provisioned resource, or when its mirrored status means the action wouldn't
	apply (e.g. stopping an already-stopped server)."""
	if not sub.asset_id:
		return
	asset = frappe.db.get_value(
		"Asset", sub.asset_id, ["resource_id", "status"], as_dict=True
	)
	if not asset or not asset.resource_id:
		return
	if asset.status not in _SERVER_ACTION_FROM.get(action, set()):
		return
	from central.api import servers

	command = servers.stop_server if action == "stop" else servers.start_server
	command(team=sub.team, resource_id=asset.resource_id)


def set_standing(subscription: str, new_standing: str, changed_by: str | None = None, reason=None):
	"""Move a subscription's account standing through the allowed transitions.

	Raises InvalidTransition for any move the state machine forbids (same-state,
	skipping the grace step, unknown standing). Records the move as an
	append-only Subscription Change. Never touches operational state.
	"""
	doc = frappe.get_doc("Subscription", subscription)
	current = doc.account_standing

	if new_standing not in _STANDING_TRANSITIONS.get(current, set()):
		raise InvalidTransition(
			f"Cannot move account standing from '{current}' to '{new_standing}'."
		)

	doc.account_standing = new_standing
	doc.save(ignore_permissions=True)
	_record_change(
		subscription,
		_STANDING_CHANGE_TYPE[new_standing],
		old_value=current,
		new_value=new_standing,
		changed_by=changed_by,
	)
	return doc


def reconcile_subscription_resource(subscription: str, resource_id: str) -> dict:
	"""Reconcile a subscription's intent against the open billing segment Central
	opened when it provisioned the resource (ADR 0010 — the ledger is the lock). No
	open segment for the resource means it hasn't been provisioned yet (intent
	outstanding); a plan mismatch is surfaced for follow-up.
	"""
	doc = frappe.get_doc("Subscription", subscription)
	seg = active_segment_for_resource(resource_id)
	if not seg:
		return {"reconciled": False, "reason": "no_cluster_event", "intent_plan": doc.plan}

	return {
		"reconciled": seg.plan == doc.plan,
		"intent_plan": doc.plan,
		"locked_plan": seg.plan,
		"resource_id": resource_id,
	}


# Deprecated agent-era name — agentless, Central writes the lock at provision time.
reconcile_with_agent_event = reconcile_subscription_resource


def backfill_missing_subscriptions():
	"""Daily job: create a Subscription for any Running Asset that lacks an
	active one (e.g. the Asset's status was set Running outside the normal flow).
	"""
	from central.billing.doctype.subscription.subscription import create_subscription

	running_assets = frappe.get_all("Asset", filters={"status": "Running"}, pluck="name")
	for asset_id in running_assets:
		has_active_subscription = frappe.db.exists(
			"Subscription", {"asset_id": asset_id, "enabled": 1}
		)
		if not has_active_subscription:
			create_subscription(asset_id)
