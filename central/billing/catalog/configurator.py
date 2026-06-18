# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Plan Configurator — generate a t-shirt-size ladder of bundles, then price it
per cluster (final-plan-pricing.md §4, §11; issue #33).

Authoring-only resource math lives *here only* — never in the data or billing
path. The ladder writes plain `quantity` / `unit` (`0.125`, `vCPU`); billing
never sees a ratio or a millicore. `1 vCPU = 1000 millicores`.

Two operations, deliberately split so the template is reusable:

1. **build / generate plans** — the doubling ladder (1/8, 1/4, … up to a ceiling),
   each rung a cluster-agnostic `Plan` (bundle) with composition. Done once.
2. **apply pricing** — `Catalog Rate` rows for a chosen cluster + currency, over
   **all or a selected subset** of the rungs (`rate = base_rate × multiplier`).
   Re-run when a new cluster onboards; rate existence per `(plan, cluster)` *is*
   the availability signal (the resolver falls regional → global, `pricing.py`).
"""

import frappe
from frappe.utils import flt

from central.billing.catalog.pricing import set_catalog_rate
from central.billing.catalog.plans import RATIO_FACTORS, configure_includes

_MAX_RUNGS = 24  # safety bound on the doubling loop

# Plan classes pre-set the memory ratio the way cloud families do (compute /
# general / memory optimised). "Custom" defers to the explicit ratio.
CLASS_RATIOS = {"CPU Optimised": "1:2", "General": "1:4", "Memory Optimised": "1:8"}


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
	name_prefix: str = "Bundle",
) -> list[dict]:
	"""The doubling size ladder from `start_vcpu` up to `ceiling_vcpu` (inclusive).

	Pure: no DB writes, no pricing. Composition is built by the shared single-plan
	helper (`plans.configure_includes`), so the ratio/memory math has one home. Each
	rung carries its plan identity, composition, and size `multiplier`
	(`vcpu / start_vcpu`) — pricing multiplies a base rate by that multiplier later.
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
		memory_gb = vcpu * factor
		disk_gb = flt(base_disk_gb) * (vcpu / start)
		includes = [
			row
			for row in configure_includes(vcpu, ratio=memory_ratio, disk_gb=disk_gb)
			if not (row["resource_type"] == "Disk" and not row["quantity"])
		]
		rungs.append(
			{
				"vcpu": vcpu,
				"memory_gb": memory_gb,
				"disk_gb": disk_gb,
				"multiplier": vcpu / start,
				"label": f"{_vcpu_label(vcpu)} · {_num(memory_gb)} GB",
				"name": f"{name_prefix} {_num(vcpu)} vCPU {_num(memory_gb)} GB",
				"includes": includes,
			}
		)
		vcpu *= 2
	return rungs


def generate_plans(rungs: list[dict], billing_cycle: str = "Monthly", is_active: int = 1) -> dict:
	"""Materialise each rung as a `Plan` + composition. Cluster-agnostic — no rates.

	Idempotent: a rung whose Plan name already exists is left untouched and
	reported under `skipped` (never overwritten).
	"""
	created, skipped = [], []
	for rung in rungs:
		if frappe.db.exists("Plan", rung["name"]):
			skipped.append(rung["name"])
			continue
		frappe.get_doc(
			{
				"doctype": "Plan",
				"__newname": rung["name"],
				"title": rung["label"],
				"billing_cycle": billing_cycle,
				"is_active": is_active,
				"includes": rung["includes"],
			}
		).insert(ignore_permissions=True)
		created.append(rung["name"])
	return {"created": created, "skipped": skipped}


def apply_pricing(
	plan_multipliers: list[dict],
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
