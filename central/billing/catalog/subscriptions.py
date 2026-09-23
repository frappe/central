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

# The account-standing state machine (which moves are legal) now lives in the one
# transition authority; re-exported so callers that catch `subscriptions.InvalidTransition`
# keep working. Suspension is still staged through Past Due (grace), never a direct jump.
from central.billing.states import InvalidTransition, transition


def anchor_subscription(team: str) -> str | None:
	"""The subscription an invoice's dunning / charge-routing anchors on.

	An invoice bills a team's whole consolidated set of servers. Account standing
	and the default payment method/gateway live on the Subscription, so dunning
	and on-charge routing need one representative subscription for the invoice:
	the team's earliest-created one. This mirrors the "primary subscription" the
	Invoice used to link to directly, before invoices became team-scoped rather
	than subscription-scoped.
	"""
	return frappe.db.get_value("Subscription", {"team": team}, "name", order_by="creation asc")


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
	opening_quote: tuple[float, str] | None = None,
):
	"""Record a subscription INTENT — what the customer asked for — linked to its
	runtime VirtualMachine. The VirtualMachine is the resource Central drives on a cluster (it carries
	the region); the Subscription is the billing contract that links to it via
	`server_id`. Billing resolves the region (and so the rate snapshot) through the
	VirtualMachine (ADR 0006, cdea38e). The actual provisioning (calling the cluster manager
	and writing the price-lock) is `provision_subscription`; this captures the
	contract + its server only, so it stays usable for fixtures and intent-only flows.

	A `Composed` subscription mints no Plan: it carries `includes` (qty per Resource
	Type) as its locked composition and `sub_category` as its optimisation profile;
	billing reads the summed config rate off its Subscription Change (ADR 0009/0010).

	The cluster must be a registered Region (VirtualMachine.cluster is a reqd Link)."""
	resource_id = resource_id or f"vm-{frappe.generate_hash(length=10)}"
	if not frappe.db.exists("Virtual Machine", resource_id):
		# Pending — not Running — so the VirtualMachine status-sync does not race us to create
		# a second Subscription for this server.
		frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": resource_id,
				"team": team,
				"cluster": cluster,
				"plan": plan,
				"status": "Pending",
				**_server_shape(includes),
			}
		).insert(ignore_permissions=True)

	doc = frappe.get_doc(
		{
			"doctype": "Subscription",
			"team": team,
			"server_id": resource_id,
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
	# A queued creation carries the price accepted before its remote dispatch.
	doc.flags.opening_quote = opening_quote
	doc.flags.changed_by = changed_by
	doc.insert(ignore_permissions=True)

	return doc


def create_server_subscription(action, resource_id: str):
	"""Open billing from the accepted quote and configuration on a Resource Action."""
	existing = frappe.db.get_value("Subscription", {"team": action.team, "server_id": resource_id}, "name")
	if existing:
		return frappe.get_doc("Subscription", existing)

	configuration = action.get_configuration()
	return create_subscription(
		action.team,
		action.atlas_instance,
		plan=configuration.plan,
		billing_cycle=configuration.billing_cycle,
		resource_id=resource_id,
		changed_by=action.requested_by,
		pricing_mode="Preset" if configuration.plan else "Composed",
		includes=None if configuration.plan else [row.model_dump() for row in configuration.includes],
		sub_category=configuration.sub_category,
		opening_quote=(action.reserved_monthly_rate, configuration.currency),
	)


def _server_shape(includes) -> dict:
	"""Record a composed config's real shape on its VirtualMachine so the running machine
	reflects what was provisioned. Empty for a preset (the Plan carries the shape)."""
	if not includes:
		return {}
	from central.billing.catalog.composition import COMPUTE, DISK, MEMORY, composition_quantities

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
		team,
		cluster,
		plan=None,
		billing_cycle=billing_cycle,
		start_date=start_date,
		default_payment_method=default_payment_method,
		gateway=gateway,
		changed_by=changed_by,
		resource_id=resource_id,
		pricing_mode="Composed",
		includes=includes,
		sub_category=sub_category,
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
		team,
		cluster,
		plan,
		billing_cycle=billing_cycle,
		start_date=start_date,
		default_payment_method=default_payment_method,
		gateway=gateway,
		changed_by=changed_by,
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

	Unlike a VM subscription, this mints no VirtualMachine and calls no cluster manager: it
	synthesizes a virtual subject per `(team, plan, cluster)`, records the intent, and
	opens the authoritative billing segment (the `Created` Subscription Change — the
	price-lock itself, ADR 0010) inline. A service subject is always alive while
	subscribed; there is no stop/start.

	The subject is keyed per (team, service *family*, cluster), not per plan, so
	upgrading to a different plan in the same family re-locks the SAME subject (a
	`Plan Changed` segment) and keeps its usage history continuous — never forking into a
	parallel subject. Re-subscribing the identical plan is idempotent. Returns the
	subscription + the synthesized subject + the locked handles."""
	category = _assert_service_plan(plan)

	subject = _service_subject_id(team, category, cluster)
	existing = frappe.db.get_value(
		"Subscription", {"service_subject": subject, "enabled": 1}, ["name", "plan"], as_dict=True
	)
	if existing:
		reused = existing.plan == plan
		if not reused:
			# Same family, different plan → an upgrade/downgrade: re-lock in place.
			change_plan(existing.name, plan, changed_by=changed_by)
		seg = _latest_segment_by_subscription([existing.name]).get(existing.name)
		return {
			"subscription": existing.name,
			"service_subject": subject,
			"reused": reused,
			"upgraded": not reused,
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
		"upgraded": False,
		"locked_rate": opening.locked_rate if opening else None,
		"currency": opening.currency if opening else None,
	}


def _assert_service_plan(plan: str) -> str:
	"""A team-level service plan is any active Plan whose family is not provisioned as a
	whole Server (servers go through the VM create/resize flow, ADR 0007). Metered
	families (AI Tokens, PDF, storage) and non-Server bundles qualify. Returns its
	Plan Category (the service family)."""
	category = frappe.db.get_value("Plan", plan, "category")
	if not category:
		frappe.throw(frappe._("Unknown plan {0}.").format(plan), frappe.ValidationError)
	if frappe.db.get_value("Plan Category", category, "provision_target") == "Server":
		frappe.throw(
			frappe._(
				"Plan {0} provisions a server — subscribe it through the server flow, not as a team-level service."
			).format(plan),
			frappe.ValidationError,
		)
	return category


def _service_subject_id(team: str, category: str, cluster: str | None) -> str:
	"""A deterministic, collision-safe virtual subject per (team, service *family*,
	cluster). Keyed on the family — not the specific plan — so an upgrade within the
	family stays on the same subject and its usage history is continuous."""
	import hashlib

	seed = f"{team}|{category}|{cluster or ''}"
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
	disk_gigabytes: int | None = None,
	changed_by: str | None = None,
) -> dict:
	"""Validate a resize and persist its durable Resource Action."""
	doc = frappe.get_doc("Subscription", subscription)
	if not _is_resizable(doc):
		return {"queued": False, "resized": False}
	server = (
		frappe.db.get_value(
			"Virtual Machine",
			doc.server_id,
			["cluster", "status", "atlas_vm_id", "title"],
			as_dict=True,
			for_update=True,
		)
		if doc.server_id
		else None
	)
	if server:
		from central.infrastructure.doctype.resource_action.resource_action import PENDING_STATES

		pending = frappe.db.get_value(
			"Resource Action",
			{"resource_id": doc.server_id, "status": ["in", PENDING_STATES]},
			"name",
		)
		if pending:
			action = frappe.get_doc("Resource Action", pending)
			if action.action == "resize":
				return {"queued": True, "resized": True, **action.customer_status()}
			frappe.throw(frappe._("Another action is still pending for this server."))

	is_live = bool(server and server.status in ("Running", "Paused", "Stopped"))
	if is_live and not server.atlas_vm_id:
		frappe.throw(frappe._("This server has no verified regional identity."))

	# A plan's own disk is what a new server is created with. Resize keeps the
	# current disk, or grows it, and refuses a plan whose disk is smaller.
	original_plan = plan
	plan, includes, sub_category = _resize_disk_choice(doc, plan, includes, sub_category, disk_gigabytes)
	# A preset grown past its own disk is now billed as a composed shape, but keeps the bundle
	# price plus the disk rate for the extra GB — never the cheaper à-la-carte total.
	preset_plan = original_plan if original_plan and plan is None else None
	override_rate = _preset_plus_disk_rate(doc, preset_plan, disk_gigabytes) if preset_plan else None
	shape = _plan_resize(doc, server, plan, includes, sub_category, override_rate)
	if shape is None:
		return {"queued": False, "resized": False}  # same config — nothing to do

	# No live VM to reshape → re-lock the contract inline (nothing slow to defer).
	if not is_live:
		if plan:
			resize_to_plan(subscription, plan, changed_by=changed_by)
		else:
			resize_composed_subscription(
				subscription,
				includes or [],
				sub_category,
				changed_by=changed_by,
				override_rate=override_rate,
				preset_plan=preset_plan,
			)
		return {"queued": False, "resized": True}

	from central.server_models import ResizeConfiguration

	configuration = ResizeConfiguration.model_validate(
		{
			"subscription": subscription,
			"plan": plan,
			"includes": includes or [],
			"sub_category": sub_category,
			"override_rate": float(override_rate) if override_rate is not None else None,
			"preset_plan": preset_plan,
			"shape": shape,
		}
	)
	action = frappe.get_doc(
		{
			"doctype": "Resource Action",
			"resource_type": "Server",
			"action": "resize",
			"team": doc.team,
			"atlas_instance": server.cluster,
			"server": doc.server_id,
			"resource_id": doc.server_id,
			"remote_vm_id": server.atlas_vm_id,
			"title": server.title or doc.server_id,
			"requested_by": changed_by or frappe.session.user,
			"correlation_id": frappe.generate_hash(length=32),
			"request_payload": configuration.model_dump(),
			"status": "Queued",
		}
	)
	# Billing validated the target and the route already checked server:resize.
	action.insert(ignore_permissions=True)
	return {"queued": True, "resized": True, **action.customer_status()}


def apply_resize_billing(action) -> None:
	"""Re-lock billing after the integration worker confirmed the target shape."""
	configuration = action.get_resize_configuration()
	if configuration.plan:
		resize_to_plan(
			configuration.subscription,
			configuration.plan,
			changed_by=action.requested_by,
		)
	else:
		resize_composed_subscription(
			configuration.subscription,
			[row.model_dump() for row in configuration.includes],
			configuration.sub_category,
			changed_by=action.requested_by,
			override_rate=configuration.override_rate,
			preset_plan=configuration.preset_plan,
		)


def _plan_resize(doc, server, plan, includes, sub_category, override_rate=None) -> dict | None:
	"""Decide a resize synchronously: return the target VM shape (vcpus/memory/disk), or
	None when it's a no-op (same config). Runs the VM-free checks — no-op detection,
	headroom, and the disk-shrink guard — so the user gets these errors immediately,
	before anything is queued; the worker re-runs them authoritatively when it applies
	the resize. (Composition validity is left to the worker.)"""
	currency = frappe.db.get_value("Billing Profile", doc.team, "currency")
	cluster = server.cluster if server else None
	if plan:
		if doc.pricing_mode == "Preset" and doc.plan == plan:
			return None
		shape = _plan_shape(plan)
		new_rate = frappe.get_doc("Plan", plan).get_rate(currency, cluster)
	else:
		from central.billing.catalog.composition import composition_quantities
		from central.billing.catalog.pricing import resolve_config_rate

		rows = [dict(r) for r in (includes or [])]
		if doc.pricing_mode == "Composed" and composition_quantities(doc.includes) == composition_quantities(
			rows
		):
			return None
		shape = _server_shape(rows)
		new_rate = resolve_config_rate(rows, currency, cluster)
	if override_rate is not None:
		new_rate = override_rate
	_enforce_resize_headroom(doc.team, new_rate, exclude=doc.name)
	if server and server.status in ("Running", "Paused", "Stopped"):
		_guard_disk_shrink(doc.server_id, shape)
	return shape


def _resize_disk_choice(doc, plan, includes, sub_category, disk_gigabytes):
	"""Apply the console's disk choice to a preset target.

	`disk_gigabytes` is omitted for an unchanged plan bundle. When it differs from
	the plan's disk, the resize becomes the plan's CPU and memory plus that disk,
	so a kept disk is not grown in passing and a grown disk is not stuck on the
	bundle price. A plan with less disk than the server already has is refused:
	storage cannot shrink, so that plan is no longer a resize target."""
	if not plan or disk_gigabytes is None:
		return plan, includes, sub_category
	disk_gigabytes = frappe.utils.cint(disk_gigabytes)
	plan_disk = _plan_shape(plan)["disk_gigabytes"]
	current_disk = (
		frappe.utils.cint(frappe.db.get_value("Virtual Machine", doc.server_id, "disk_gigabytes"))
		if doc.server_id
		else 0
	)
	if plan_disk < current_disk:
		frappe.throw(
			frappe._(
				"Disk can't shrink: this server has a {0} GB disk, so it cannot move to a smaller plan."
			).format(current_disk)
		)
	if disk_gigabytes == plan_disk:
		return plan, includes, sub_category
	rows = _plan_includes(plan)
	replaced = False
	for row in rows:
		if row["resource_type"] == "Disk":
			row["quantity"] = disk_gigabytes
			replaced = True
	if not replaced:
		rows.append({"resource_type": "Disk", "quantity": disk_gigabytes, "unit": "GB"})
	profile = frappe.db.get_value("Plan", plan, "sub_category") or sub_category
	return None, [dict(row) for row in rows], profile


def _plan_includes(plan: str) -> list:
	return frappe.get_all(
		"Plan Includes",
		filters={"parenttype": "Plan", "parent": plan},
		fields=["resource_type", "quantity", "unit"],
		order_by="idx asc",
	)


def _preset_plus_disk_rate(doc, plan: str, disk_gigabytes) -> float | None:
	"""A preset's bundle price plus the disk rate for the GB grown beyond the plan's own disk.
	Growing disk on a preset therefore always adds to the price, instead of dropping to the
	cheaper à-la-carte total. Returns None if the plan has no rate in the team's currency."""
	from central.billing.catalog.pricing import resolve_component_rate

	currency = frappe.db.get_value("Billing Profile", doc.team, "currency")
	cluster = frappe.db.get_value("Virtual Machine", doc.server_id, "cluster") if doc.server_id else None
	base = frappe.get_doc("Plan", plan).get_rate(currency, cluster)
	if base is None:
		return None
	extra = max(0, frappe.utils.cint(disk_gigabytes) - _plan_shape(plan)["disk_gigabytes"])
	if not extra:
		return base
	return base + extra * frappe.utils.flt(resolve_component_rate("Disk", currency, cluster) or 0)


def resize_composed_subscription(
	subscription: str,
	includes: list,
	sub_category: str | None = None,
	changed_by: str | None = None,
	override_rate: float | None = None,
	preset_plan: str | None = None,
):
	"""Resize a composed config — or slide a preset onto a custom shape — as the
	`changed`-event re-lock (#82, ADR 0010).

	Closes the open segment and opens a new one whose `locked_rate` is the config
	total **re-resolved at the current rate card**; grandfathering protects only the
	*unchanged* config. The new shape is validated against its profile (#81) and the
	team's remaining headroom before anything is written. A no-op on an identical
	composition (matching #54), and records nothing on a never-provisioned or
	terminated config. `preset_plan` names the preset whose CPU and memory the shape
	keeps with a larger disk.
	"""
	doc = frappe.get_doc("Subscription", subscription)
	if not _is_resizable(doc):
		return None

	profile = sub_category or doc.sub_category
	if not profile:
		frappe.throw(frappe._("A composed config needs an optimisation profile."))

	rows = [dict(r) for r in includes]
	from central.billing.catalog.composition import composition_quantities
	from central.billing.catalog.pricing import resolve_config_rate

	_validate_resize_shape(profile, rows, doc.server_id, preset_plan)

	currency = frappe.db.get_value("Billing Profile", doc.team, "currency")
	server = (
		frappe.db.get_value("Virtual Machine", doc.server_id, ["cluster"], as_dict=True)
		if doc.server_id
		else None
	)
	# A preset grown past its own disk keeps the bundle price plus the extra disk; a genuine
	# composed shape is priced à la carte. The headroom check uses whichever will be billed.
	new_rate = (
		override_rate
		if override_rate is not None
		else resolve_config_rate(rows, currency, server.cluster if server else None)
	)
	_enforce_resize_headroom(doc.team, new_rate, exclude=subscription)

	# Resizing to the identical composition already running is a no-op (no event).
	if doc.pricing_mode == "Composed" and composition_quantities(doc.includes) == composition_quantities(
		rows
	):
		return doc

	doc.pricing_mode = "Composed"
	doc.plan = None
	doc.sub_category = profile
	doc.set("includes", rows)
	doc.flags.changed_by = changed_by
	# Lock the new segment at the bundle-plus-disk price rather than the à-la-carte total.
	if override_rate is not None:
		doc.flags.locked_rate_override = (override_rate, currency)
	doc.save(ignore_permissions=True)  # controller appends the Plan Changed re-lock
	return doc


def resize_to_plan(
	subscription: str,
	new_plan: str,
	changed_by: str | None = None,
):
	"""Re-lock a server subscription on a preset after its resize is confirmed."""
	doc = frappe.get_doc("Subscription", subscription)
	if not _is_resizable(doc):
		return None
	if doc.pricing_mode == "Preset" and doc.plan == new_plan:
		return doc
	server = (
		frappe.db.get_value("Virtual Machine", doc.server_id, ["cluster"], as_dict=True)
		if doc.server_id
		else None
	)
	# Refuse a resize that would push the team past its trust-tier headroom — the same
	# gate resize_composed_subscription applies, so a preset target can't slip past the
	# spend cap. Authoritative here (covers every caller, incl. the background job);
	# begin_resize also checks it synchronously for immediate feedback.
	currency = frappe.db.get_value("Billing Profile", doc.team, "currency")
	new_rate = frappe.get_doc("Plan", new_plan).get_rate(currency, server.cluster if server else None)
	_enforce_resize_headroom(doc.team, new_rate, exclude=subscription)
	return change_plan(subscription, new_plan, changed_by=changed_by)


def _plan_shape(plan: str) -> dict:
	"""A preset Plan's bundled size as the _server_shape dict (vcpus/memory/disk)."""
	includes = frappe.get_all(
		"Plan Includes",
		filters={"parenttype": "Plan", "parent": plan},
		fields=["resource_type", "quantity"],
	)
	return _server_shape(includes)


def _validate_resize_shape(
	profile: str, rows: list, server_id: str | None, preset_plan: str | None = None
) -> None:
	"""Validate a resize shape. A disk the server already has may sit below the
	profile minimum. CPU and memory the server runs now, or that `preset_plan` sells,
	need only the disk checks, even when that shape is not what a new config would
	be allowed to design."""
	from central.billing.catalog.composition import (
		COMPUTE,
		DISK,
		MEMORY,
		composition_quantities,
		validate_composition,
	)

	if not server_id:
		validate_composition(profile, rows)
		return
	current = (
		frappe.db.get_value(
			"Virtual Machine", server_id, ["vcpus", "memory_megabytes", "disk_gigabytes"], as_dict=True
		)
		or frappe._dict()
	)
	qty = composition_quantities(rows)
	current_disk = frappe.utils.cint(current.disk_gigabytes)
	new_disk = frappe.utils.flt(qty.get(DISK, 0))
	same_compute = frappe.utils.flt(qty.get(COMPUTE, 0)) == frappe.utils.flt(current.vcpus) and (
		frappe.utils.flt(qty.get(MEMORY, 0)) == frappe.utils.flt(current.memory_megabytes) / 1024
	)
	if same_compute or preset_plan:
		_guard_disk_shrink(server_id, {"disk_gigabytes": int(new_disk)})
		disk_max = frappe.utils.flt(frappe.db.get_value("Plan Sub-Category", profile, "disk_max"))
		if disk_max and new_disk > disk_max:
			frappe.throw(
				frappe._("Disk {0} GB exceeds the {1} maximum of {2} GB.").format(
					frappe.utils.flt(new_disk), profile, disk_max
				)
			)
		return
	disk_min = frappe.utils.flt(frappe.db.get_value("Plan Sub-Category", profile, "disk_min"))
	check_rows = rows
	if new_disk == current_disk and disk_min and new_disk < disk_min:
		check_rows = [
			{**row, "quantity": disk_min} if row.get("resource_type") == DISK else dict(row) for row in rows
		]
	validate_composition(profile, check_rows)


def _enforce_resize_headroom(team: str, new_rate, exclude: str | None = None) -> None:
	"""Staging trials are not spend-capped on resize. The menu already shows the
	full catalog, and the trial is bounded by credits rather than trust-tier headroom."""
	if frappe.db.get_value("Team", team, "is_staging_trial"):
		if new_rate is None:
			frappe.throw(frappe._("This configuration cannot be priced in your currency."))
		return
	enforce_headroom(team, new_rate, exclude=exclude)


def _guard_disk_shrink(server_id: str, shape: dict) -> None:
	"""Refuse a resize that would shrink the disk — Atlas can only grow a rootfs. Cheap
	and VM-free, so `begin_resize` runs it synchronously to surface the error to the user
	before the slow reshape is ever queued."""
	if not shape:
		return
	current_disk = frappe.utils.cint(frappe.db.get_value("Virtual Machine", server_id, "disk_gigabytes"))
	if shape["disk_gigabytes"] < current_disk:
		frappe.throw(
			frappe._(
				"Disk can't shrink: this server has a {0} GB disk — choose a size with at least that much storage."
			).format(current_disk)
		)


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
	if doc.server_id and frappe.db.get_value("Virtual Machine", doc.server_id, "status") == "Terminated":
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


def _server_clusters(server_ids) -> dict:
	"""Map server_id -> cluster in one query (cluster lives on the VirtualMachine, cdea38e)."""
	ids = [a for a in set(server_ids) if a]
	if not ids:
		return {}
	return {
		r.name: r.cluster
		for r in frappe.get_all("Virtual Machine", filters={"name": ["in", ids]}, fields=["name", "cluster"])
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
	pricing_mode, server_id, resource_id, cluster, currency, locked_rate."""
	subs = frappe.get_all(
		"Subscription",
		filters=filters or {},
		fields=["name", "team", "plan", "pricing_mode", "server_id", "service_subject", "cluster"],
	)
	if not subs:
		return []
	latest = _latest_segment_by_subscription([s.name for s in subs])
	clusters = _server_clusters([s.server_id for s in subs])
	out = []
	for s in subs:
		seg = latest.get(s.name)
		if not seg or seg.change_type == "Cancelled":
			continue
		# A VM subscription is subjected by its VirtualMachine (cluster off the VirtualMachine); a
		# team-level service subject has no VirtualMachine — its id and cluster live on the
		# Subscription itself (ADR 0013). Either way the resource_id keys metering.
		resource_id = s.server_id or s.service_subject
		out.append(
			frappe._dict(
				{
					"subscription": s.name,
					"team": s.team,
					"plan": s.plan,
					"pricing_mode": s.pricing_mode,
					"server_id": s.server_id,
					"service_subject": s.service_subject,
					"resource_id": resource_id,
					"cluster": clusters.get(s.server_id) or s.cluster,
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
	by its VirtualMachine (`server_id`); a team-level service subject is named by the synthesized
	`service_subject` (ADR 0013). Either maps to at most one subscription. Used by
	metering to grandfather a subject's terms off the ledger (#86)."""
	segs = active_segments({"server_id": resource_id})
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
		sum(s.locked_rate for s in active_segments({"team": team, "enabled": 1}) if s.subscription != exclude)
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


def project_run_rate(team: str, project: str, exclude: str | None = None) -> float:
	"""A project's committed monthly run-rate: the summed open-segment locked rate of
	the team's subscriptions tagged into it. Mirrors `team_run_rate`, scoped to one
	project's tag instead of the whole team."""
	return frappe.utils.flt(
		sum(
			s.locked_rate
			for s in active_segments({"team": team, "project": project, "enabled": 1})
			if s.subscription != exclude
		)
	)


def enforce_project_headroom(team: str, project: str | None, new_rate, exclude: str | None = None) -> None:
	"""Reject tagging a new server into a project that would push its committed
	run-rate past its `spending_limit` (0/unset = unlimited). Blocks new servers
	only (the breaking-change spec) — an already-tagged subscription keeps running
	untouched even if the limit is lowered afterward."""
	if not project:
		return
	limit = frappe.utils.flt(frappe.db.get_value("Project", project, "spending_limit"))
	if not limit:
		return
	if new_rate is None:
		frappe.throw(frappe._("This configuration cannot be priced in your currency."))
	available = max(0.0, limit - project_run_rate(team, project, exclude=exclude))
	if frappe.utils.flt(new_rate) > available:
		frappe.throw(
			frappe._(
				"Tagging this server into the project would exceed its spending limit "
				"({0} committed, {1} available)."
			).format(frappe.utils.flt(new_rate), frappe.utils.flt(available))
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
	if not sub.server_id:
		return
	server = frappe.db.get_value("Virtual Machine", sub.server_id, ["resource_id", "status"], as_dict=True)
	if not server or not server.resource_id:
		return
	if server.status not in _SERVER_ACTION_FROM.get(action, set()):
		return
	from central.api import servers

	command = servers.stop_server if action == "stop" else servers.start_server
	command(team=sub.team, resource_id=server.resource_id)


def set_standing(subscription: str, new_standing: str, changed_by: str | None = None, reason=None):
	"""Move a subscription's account standing through the allowed transitions.

	Routes the move through the transition authority: it raises InvalidTransition for a
	forbidden move (skipping the grace step, an unknown standing) and appends a Billing
	Event. A move to the current standing is an idempotent no-op — dunning re-applies the
	same standing on each retry day and must not error or record a spurious change. The
	move is also recorded as an append-only Subscription Change (the load-bearing ledger).
	"""
	doc = frappe.get_doc("Subscription", subscription)
	current = doc.account_standing
	if current == new_standing:
		return

	transition(doc, new_standing, reason=reason, actor=changed_by)
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
	"""Daily job: create a Subscription for any Running VirtualMachine that lacks an
	active one (e.g. the VirtualMachine's status was set Running outside the normal flow).
	"""
	from central.billing.doctype.subscription.subscription import create_subscription

	running_servers = frappe.get_all("Virtual Machine", filters={"status": "Running"}, pluck="name")
	for server_id in running_servers:
		has_active_subscription = frappe.db.exists("Subscription", {"server_id": server_id, "enabled": 1})
		if not has_active_subscription:
			create_subscription(server_id)
