# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Plan Configurator — propose a t-shirt-size ladder of bundles, let the admin
tune it, then generate the Plans and price them per cluster (final-plan-pricing.md
§4, §11; issue #33).

Authoring-only resource math lives *here only* — never in the data or billing
path. Generated Plans carry plain `quantity` / `unit` (`2`, `vCPU`); billing never
sees a ratio or a millicore. `1 vCPU = 1000 millicores`.

The flow is deliberately split so curated, real-world catalogues (à la the cloud
"Droplet plan" families) are reachable, not just clean formulae:

1. **build_ladder** — the doubling proposal (start → ceiling): vCPU doubles, memory
   = vCPU × ratio, disk scales with the size multiplier, transfer steps additively,
   price = base_rate × multiplier. The admin edits these rungs (irregular transfer,
   off-ratio memory, even a hand-authored Basic tier) before generating.
2. **generate_plans** — one cluster-agnostic `Plan` + composition per (edited) rung.
3. **apply_pricing** — `Catalog Rate` rows for a cluster + currency over all or a
   selected subset of the rungs. Rate existence per `(plan, cluster)` *is* the
   availability signal (the resolver falls regional → global, `pricing.py`).
"""

import frappe
from frappe.utils import flt

from central.billing.catalog.pricing import set_catalog_rate
from central.billing.catalog.plans import RATIO_FACTORS

_MAX_RUNGS = 24  # safety bound on the doubling loop

# Plan classes pre-set the memory ratio the way cloud families do. "Custom" defers
# to the explicit ratio. Storage- and memory-optimised share 1:8; they differ by
# disk, which the admin sets via the base disk (and edits per rung).
CLASS_RATIOS = {
	"CPU Optimised": "1:2",
	"General": "1:4",
	"Memory Optimised": "1:8",
	"Storage Optimised": "1:8",
}


def ratio_for(plan_class: str | None, memory_ratio: str) -> str:
	"""The effective ratio: a class pins it; "Custom"/blank uses the explicit one."""
	if plan_class and plan_class != "Custom":
		return CLASS_RATIOS[plan_class]
	return memory_ratio


def build_ladder(
	start_vcpu: float,
	ceiling_vcpu: float,
	memory_ratio: str,
	base_disk_gb: float = 0,
	base_transfer_gb: float = 0,
	transfer_step_gb: float = 0,
	name_prefix: str = "Bundle",
) -> list[dict]:
	"""The doubling-ladder proposal from `start_vcpu` up to `ceiling_vcpu` (inclusive).

	Pure: no DB writes. Each rung carries its identity and a full set of *editable*
	values — vCPU, memory, disk, transfer, and the price `multiplier`
	(`vcpu / start_vcpu`). Memory = vCPU × ratio; disk scales with the multiplier;
	transfer steps additively (`base + index × step`, since real transfer tiers are
	rarely a clean multiple). The admin may overwrite any of these before generating.
	"""
	start = flt(start_vcpu)
	ceiling = flt(ceiling_vcpu)
	factor = RATIO_FACTORS.get(memory_ratio)
	if not factor:
		frappe.throw(f"Memory ratio must be one of {', '.join(RATIO_FACTORS)}.")
	if start <= 0:
		frappe.throw("Start vCPU must be greater than zero.")
	if ceiling < start:
		frappe.throw("Ceiling vCPU must be at least the start vCPU.")

	rungs = []
	vcpu = start
	while vcpu <= ceiling * (1 + 1e-9) and len(rungs) < _MAX_RUNGS:
		index = len(rungs)
		memory_gb = vcpu * factor
		rungs.append(
			{
				"vcpu": vcpu,
				"memory_gb": memory_gb,
				"disk_gb": flt(base_disk_gb) * (vcpu / start),
				"transfer_gb": flt(base_transfer_gb) + index * flt(transfer_step_gb),
				"multiplier": vcpu / start,
				**rung_identity(vcpu, memory_gb, name_prefix),
			}
		)
		vcpu *= 2
	return rungs


def rung_identity(vcpu: float, memory_gb: float, name_prefix: str = "Bundle") -> dict:
	"""The Plan name + human label for a rung — shared by the formula and by
	manually-added rows so a hand-inserted size (e.g. 1 vCPU 3 GB) names itself."""
	return {
		"plan_name": f"{name_prefix} {_num(vcpu)} vCPU {_num(memory_gb)} GB",
		"label": f"{_vcpu_label(vcpu)} · {_num(memory_gb)} GB",
	}


def rung_includes(vcpu: float, memory_gb: float, disk_gb: float, transfer_gb: float) -> list[dict]:
	"""Plain composition rows for one (already-resolved) rung — what billing reads.
	No price, no millicores. Disk / transfer lines are dropped when zero."""
	rows = [
		{"resource_type": "Compute", "quantity": flt(vcpu), "unit": "vCPU"},
		{"resource_type": "Memory", "quantity": flt(memory_gb), "unit": "GB"},
	]
	if flt(disk_gb) > 0:
		rows.append({"resource_type": "Disk", "quantity": flt(disk_gb), "unit": "GB"})
	if flt(transfer_gb) > 0:
		rows.append({"resource_type": "Transfer", "quantity": flt(transfer_gb), "unit": "GB"})
	return rows


def generate_plans(plan_class: str | None, rungs: list, billing_cycle: str = "Monthly", is_active: int = 1) -> dict:
	"""Materialise each (edited) rung as a `Plan` + composition. Cluster-agnostic.

	Idempotent: a rung whose Plan name already exists is left untouched and reported
	under `skipped` (never overwritten). Accepts dicts or child-table rows.
	"""
	created, skipped = [], []
	for rung in rungs:
		g = rung.get if isinstance(rung, dict) else lambda k: getattr(rung, k)
		name = g("plan_name")
		if frappe.db.exists("Plan", name):
			skipped.append(name)
			continue
		# vm_rungs always authors the VM Plans family; plan_class is its optimization
		# profile, now a Plan Sub-Category (Custom carries none). #76 folds this into
		# the category-aware builder dispatch.
		sub_category = (
			plan_class
			if plan_class and plan_class != "Custom" and frappe.db.exists("Plan Sub-Category", plan_class)
			else None
		)
		frappe.get_doc(
			{
				"doctype": "Plan",
				"__newname": name,
				"title": g("label") or name,
				"category": "VM Plans",
				"sub_category": sub_category,
				"billing_cycle": billing_cycle,
				"is_active": is_active,
				"includes": rung_includes(g("vcpu"), g("memory_gb"), g("disk_gb"), g("transfer_gb")),
			}
		).insert(ignore_permissions=True)
		created.append(name)
	return {"created": created, "skipped": skipped}


def apply_pricing(
	plan_multipliers: list,
	currency: str,
	base_rate: float,
	cluster: str | None = None,
) -> dict:
	"""Upsert one `Catalog Rate` per plan for `(cluster, currency)`.

	`plan_multipliers`: rows with `plan` (name) and `multiplier`. Rate is
	`base_rate × multiplier`. Blank `cluster` = the global default (available on
	every cluster via the resolver's fallback); a set cluster prices only there.
	Re-applying updates the rate in place (a deliberate re-price), never touching
	other clusters' rows. Returns names created vs updated.
	"""
	if not currency:
		frappe.throw("Currency is required.")
	if flt(base_rate) <= 0:
		frappe.throw("Base rate must be greater than zero.")

	created, updated = [], []
	for row in plan_multipliers:
		plan = row["plan"] if isinstance(row, dict) else row.plan
		multiplier = row["multiplier"] if isinstance(row, dict) else row.multiplier
		rate = flt(flt(base_rate) * flt(multiplier), 2)
		_, was_created = set_catalog_rate("Plan", plan, currency, rate, cluster=cluster)
		(created if was_created else updated).append(plan)
	return {"created": created, "updated": updated, "cluster": cluster or None, "currency": currency}


def _vcpu_label(v: float) -> str:
	"""Human size: '1/8 vCPU', '1/2 vCPU', '2 vCPU'."""
	if v >= 1:
		return f"{_num(v)} vCPU"
	inv = 1 / v
	if abs(inv - round(inv)) < 1e-6:
		return f"1/{round(inv)} vCPU"
	return f"{_num(v)} vCPU"


def _num(v: float) -> str:
	"""Trim trailing zeros: 2.0 -> '2', 0.125 -> '0.125'."""
	return f"{flt(v):g}"
