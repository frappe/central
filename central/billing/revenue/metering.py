# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Central metered-usage ingestion + billing (issue #12).

Central stores only the Agent's rollups — never a raw sample — so the row count
stays bounded (~one metered line per resource per meter per month).

A metered resource is priced by its **metered single-resource Plan** — a Plan under a
`Metered` Plan Category whose composition is exactly one include matching the resource
type (ADR 0008, which retired the standalone Add-on). The family's `pricing_mode`
selects one of two modes:
  - **Grandfathered** (default): `max(0, quantity - locked_allowance) x locked_rate`,
    where the allowance (the base plan's included baseline) and the per-unit rate are
    locked at ingest, exactly like fixed prices are grandfathered by the price-lock.
  - **Live** (e.g. snapshot — depreciating storage): no allowance and the rate is
    read from the CURRENT Catalog Rate each billing period, never locked. A live
    resource has its own resource_id from birth and needs no price-lock to bill,
    so it survives VM termination.
"""

import frappe

from central.billing.catalog.pricing import get_catalog_rates, resolve_rate


def _metered_plan_for(resource_type: str):
	"""The active metered single-resource Plan for a resource_type, with its family's
	`pricing_mode`. None if no metered Plan models the resource.

	A metered Plan is one under a `Metered` Plan Category whose composition is a single
	`Plan Includes` row. `Plan.validate` guarantees at most one *active* such Plan per
	resource type (ADR 0008), so resolution is unambiguous.
	"""
	metered_cats = {
		c.name: c.pricing_mode
		for c in frappe.get_all(
			"Plan Category", filters={"billing_type": "Metered"}, fields=["name", "pricing_mode"]
		)
	}
	if not metered_cats:
		return None

	plans = frappe.get_all(
		"Plan", filters={"category": ["in", list(metered_cats)], "is_active": 1}, fields=["name", "category"]
	)
	if not plans:
		return None

	includes = frappe.get_all(
		"Plan Includes",
		filters={"parent": ["in", [p.name for p in plans]]},
		fields=["parent", "resource_type"],
	)
	by_plan: dict[str, list[str]] = {}
	for inc in includes:
		by_plan.setdefault(inc.parent, []).append(inc.resource_type)

	for p in plans:
		rts = by_plan.get(p.name, [])
		if len(rts) == 1 and rts[0] == resource_type:
			return frappe._dict({"name": p.name, "pricing_mode": metered_cats[p.category]})
	return None


def _resolve_terms(meter: dict):
	"""Ingest-time terms for a rollup, branching on the metered family's pricing mode.

	- **Live** (e.g. snapshot): no price-lock needed — a live metered resource has its
	  own resource_id from birth and survives VM termination. team/cluster/currency
	  come from the meter payload; there is NO allowance and NO locked rate (the
	  rate is read live at billing). See ADR 0002.
	- **Grandfathered**: the locked allowance + per-unit rate off the resource's
	  active price-lock (skipped when there is no active lock).
	"""
	plan = _metered_plan_for(meter.get("resource_type"))
	if plan and plan.pricing_mode == "Live":
		return {
			"team": meter.get("team"),
			"cluster": meter.get("cluster"),
			"currency": meter.get("currency"),
			"allowance": 0,
			"rate": 0,
		}
	return _locked_terms(meter.get("resource_id"), meter.get("resource_type"))


def _locked_terms(resource_id: str, resource_type: str):
	"""Resolve the locked allowance + per-unit rate for a metered resource.

	Keyed off the resource's open billing segment (ADR 0010 — the ledger is the lock),
	which carries the team, currency and base plan; the cluster comes from its Asset.
	The allowance is the base plan's included quantity for the resource_type
	(grandfathered via the plan's immutable identity); the rate is the matching metered
	single-resource Plan's per-unit rate for that currency + cluster. Returns None when
	the resource has no open segment (nothing to bill against).
	"""
	from central.billing.catalog.subscriptions import active_segment_for_resource

	seg = active_segment_for_resource(resource_id)
	if not seg:
		return None

	allowance = 0
	if seg.plan and frappe.db.exists("Plan", seg.plan):
		plan = frappe.get_doc("Plan", seg.plan)
		for inc in plan.includes:
			if inc.resource_type == resource_type:
				allowance = frappe.utils.flt(inc.quantity)
				break

	rate = 0
	plan = _metered_plan_for(resource_type)
	if plan:
		rate = frappe.utils.flt(
			resolve_rate(get_catalog_rates("Plan", plan.name), seg.currency, seg.cluster)
		)

	return {
		"team": seg.team,
		"cluster": seg.cluster,
		"currency": seg.currency,
		"allowance": allowance,
		"rate": rate,
	}


def _reporting_mode_for(resource_type: str) -> str:
	"""The reporting mode of the family that prices `resource_type` (ADR 0015), blank
	resolving to Authoritative. A resource type maps to at most one active metered Plan
	(ADR 0008), whose Plan Category carries the mode — so this is unambiguous."""
	plan = _metered_plan_for(resource_type)
	if not plan:
		return "Authoritative"
	category = frappe.db.get_value("Plan", plan.name, "category")
	return frappe.db.get_value("Plan Category", category, "reporting_mode") or "Authoritative"


def _settlement_mode_for(resource_type: str) -> str:
	"""The settlement mode of the family that prices `resource_type` (ADR 0015), blank
	resolving to Postpaid Overage. Prepaid Pack usage is not billed as overage — the
	pack was paid up front and excess is blocked at the edge, not charged."""
	plan = _metered_plan_for(resource_type)
	if not plan:
		return "Postpaid Overage"
	category = frappe.db.get_value("Plan", plan.name, "category")
	return frappe.db.get_value("Plan Category", category, "settlement_mode") or "Postpaid Overage"


def ingest_rollup(meter: dict) -> str | None:
	"""Idempotently store one meter rollup, keyed by the period-identity idempotency_key.
	Both reporting modes (ADR 0015) land as one Usage Rollup row per period; the locked
	allowance + rate are stamped once, at first receipt, so the metered terms are
	grandfathered and a later catalog change cannot move an existing rollup's price.

	- **Authoritative** (default): a re-push REPLACES the period quantity (recompute
	  after an outage), never adds — the reporter holds the authoritative total.
	- **Incremental**: each batch carries a `quantity` delta and a monotonic `sequence`.
	  A batch is ACCUMULATED (`quantity += delta`) only if its sequence exceeds the last
	  applied, so a retried/duplicate/out-of-order batch is a no-op.

	Concurrency: an existing row is locked FOR UPDATE while it is applied, so concurrent
	batches serialize. The FIRST report can't lock a not-yet-existent row, so two
	first-reports for the same period both miss and race to insert — the loser hits the
	unique idempotency_key. We roll that failed insert back to a SAVEPOINT (not the whole
	batch), then loop: the retry re-reads FOR UPDATE (blocking on the winner), so its
	figure is applied to the winner's row instead of being dropped.

	Returns the idempotency_key once handled (so the reporter can mark it synced)."""
	key = meter.get("idempotency_key")
	if not key:
		return None

	mode = _reporting_mode_for(meter.get("resource_type"))
	qty = frappe.utils.flt(meter.get("quantity"))
	seq = frappe.utils.cint(meter.get("sequence"))

	for _ in range(_INGEST_RACE_RETRIES):
		existing = frappe.db.get_value(
			"Usage Rollup", {"idempotency_key": key}, ["name", "quantity", "sequence"],
			as_dict=True, for_update=True,
		)
		if existing:
			_apply_report(existing, mode, qty, seq)
			return key

		terms = _resolve_terms(meter)
		if not terms:
			return None  # no active lock — nothing to bill this against yet

		try:
			frappe.db.savepoint("usage_rollup_insert")
			_insert_rollup(meter, terms, qty, seq, key)
			return key
		except frappe.DuplicateEntryError:
			# Lost the first-insert race: a concurrent first report created the row between
			# our lock-miss and our insert. Undo only our failed insert (keep the rest of
			# the batch), then loop — the re-read FOR UPDATE blocks on the winner and our
			# figure lands on its row rather than being dropped.
			frappe.db.rollback(save_point="usage_rollup_insert")
	return key


# A first-insert race resolves in one retry; a couple more absorb a winner that rolls
# back after we saw its lock (leaving the row briefly gone again).
_INGEST_RACE_RETRIES = 3


def _apply_report(existing, mode: str, qty: float, seq: int) -> None:
	"""Apply a report to the already-locked rollup row. Authoritative replaces the period
	figure; Incremental accumulates only when the sequence advances (else a no-op)."""
	if mode == "Incremental":
		if seq <= frappe.utils.cint(existing.sequence):
			return  # duplicate / out-of-order batch — already counted
		frappe.db.set_value(
			"Usage Rollup", existing.name,
			{"quantity": frappe.utils.flt(existing.quantity) + qty, "sequence": seq},
		)
	else:
		# Authoritative: replace the period figure; the locked terms stay as first stamped.
		frappe.db.set_value("Usage Rollup", existing.name, "quantity", qty)


def _insert_rollup(meter: dict, terms: dict, qty: float, seq: int, key: str) -> None:
	"""Insert the period's rollup with its billing terms stamped once, at first receipt."""
	frappe.get_doc(
		{
			"doctype": "Usage Rollup",
			"resource_id": meter.get("resource_id"),
			"team": terms["team"],
			"cluster": terms["cluster"],
			"resource_type": meter.get("resource_type"),
			"meter_type": meter.get("meter_type"),
			"period_start": meter.get("period_start"),
			"period_end": meter.get("period_end"),
			"quantity": qty,
			"unit": meter.get("unit"),
			"currency": terms["currency"],
			"locked_allowance": terms["allowance"],
			"locked_rate": terms["rate"],
			"idempotency_key": key,
			"sequence": seq,
		}
	).insert(ignore_permissions=True)


def metered_line_items(team: str, cluster: str, period_start, period_end) -> list[dict]:
	"""Metered line items for a (team, cluster) over the billing month.

	One line per rollup whose period falls in the billing month:
	`max(0, quantity - locked_allowance) x locked_rate`. A rollup entirely
	within the allowance contributes no line.
	"""
	period_start = frappe.utils.getdate(period_start)
	period_end = frappe.utils.getdate(period_end)

	rollups = frappe.get_all(
		"Usage Rollup",
		filters={"team": team, "cluster": cluster},
		fields=[
			"resource_id", "resource_type", "meter_type", "quantity", "unit", "currency",
			"locked_allowance", "locked_rate", "period_start",
		],
	)

	lines = []
	unpriced = []  # (resource_type, reason) — collected so every problem surfaces at once
	for r in rollups:
		if r.period_start and not (period_start <= frappe.utils.getdate(r.period_start) <= period_end):
			continue

		# A prepaid-pack family bills nothing here: the pack was paid up front and usage
		# beyond it is blocked at the edge, not charged as overage (ADR 0015).
		if _settlement_mode_for(r.resource_type) == "Prepaid Pack":
			continue

		# A live metered plan (e.g. snapshot) reads the CURRENT catalog rate and has no
		# allowance; a grandfathered one uses the terms locked at ingest. `resolved`
		# stays None (not 0) when no rate is configured, so an unpriced overage is
		# distinguishable from a genuinely free one below.
		plan = _metered_plan_for(r.resource_type)
		if plan and plan.pricing_mode == "Live":
			resolved = resolve_rate(get_catalog_rates("Plan", plan.name), r.currency, cluster)
			allowance = 0.0
		else:
			resolved = r.locked_rate
			allowance = frappe.utils.flt(r.locked_allowance)

		billable_qty = max(0.0, frappe.utils.flt(r.quantity) - allowance)
		if billable_qty <= 0:
			continue

		# Usage ran past the allowance, so the overage must resolve to a rate. Surface the
		# two misconfigurations distinctly (a missing rate row must not read as a missing
		# plan during an outage investigation), and don't bill either silently at zero:
		#   - resolved is None: a live plan exists but has no Catalog Rate for this
		#     currency/cluster (the grandfathered branch always carries a locked number).
		#   - rate is 0 with no plan modelling the resource: nothing prices the overage.
		# A rate that *is* configured at 0 with a plan present is a legitimate free tier and
		# falls through to a zero-amount line (ADR 0008).
		if resolved is None:
			unpriced.append(
				(
					r.resource_type,
					frappe._("metered plan {0} has no rate for {1} / {2}").format(
						plan.name, r.currency, cluster or frappe._("default cluster")
					),
				)
			)
			continue

		rate = frappe.utils.flt(resolved)
		if rate == 0 and plan is None:
			unpriced.append((r.resource_type, frappe._("no active metered plan prices it")))
			continue

		amount = frappe.utils.flt(billable_qty * rate, 2)
		lines.append(
			{
				"subscription_resource": r.resource_id,
				"plan": None,
				"cluster": cluster,
				"resource_type": r.resource_type,
				"unit": r.unit,
				"quantity": billable_qty,
				"rate": rate,
				"days": 0,
				"amount": amount,
			}
		)

	if unpriced:
		frappe.throw(
			frappe._("Cannot bill team {0} — unpriced metered usage: {1}.").format(
				team, "; ".join(frappe._("{0} ({1})").format(rt, why) for rt, why in unpriced)
			)
		)
	return lines
