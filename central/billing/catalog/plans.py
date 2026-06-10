# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Live plan pricing reads.

Pricing is read live at purchase (human pace), locked at provision, and frozen
for billing (machine pace). This module serves the first role only.
"""

import frappe

# Memory-ratio pre-fills for the Plan Configurator (issue #33). Authoring-only:
# the ratio derives a default memory; the resulting GB is what's stored, never
# the ratio itself. 1 vCPU = 1000 millicores is the configurator's notion only.
RATIO_FACTORS = {"1:2": 2, "1:4": 4}


def configure_includes(vcpu: float, ratio: str = "1:2", disk_gb: float = 0, memory_gb: float | None = None) -> list[dict]:
	"""Build plain Plan Includes rows from configurator inputs.

	Memory is pre-filled from the ratio (`vcpu × factor`) unless `memory_gb`
	overrides it — the ratio is a default, not a constraint, so off-ratio bundles
	(e.g. 1 vCPU + 3 GB) are allowed. Returns composition rows carrying only
	quantity/unit (no price, no millicores, no ratio).
	"""
	vcpu = frappe.utils.flt(vcpu)
	if ratio not in RATIO_FACTORS:
		frappe.throw(f"Unknown memory ratio {ratio!r}; expected one of {sorted(RATIO_FACTORS)}.")
	memory = frappe.utils.flt(memory_gb) if memory_gb is not None else frappe.utils.flt(vcpu * RATIO_FACTORS[ratio])
	return [
		{"resource_type": "compute", "quantity": vcpu, "unit": "vCPU"},
		{"resource_type": "memory", "quantity": memory, "unit": "GB"},
		{"resource_type": "disk", "quantity": frappe.utils.flt(disk_gb), "unit": "GB"},
	]


@frappe.whitelist()
def create_configured_plan(
	name: str,
	title: str,
	vcpu: float,
	ratio: str = "1:2",
	disk_gb: float = 0,
	memory_gb: float | None = None,
	billing_cycle: str = "monthly",
) -> str:
	"""Create a bundle Plan from configurator inputs; return its name.

	Writes the derived composition into Plan Includes. Rates are authored
	separately as Catalog Rate documents (#27) — out of scope here.
	"""
	includes = configure_includes(vcpu, ratio=ratio, disk_gb=disk_gb, memory_gb=memory_gb)
	doc = frappe.get_doc(
		{
			"doctype": "Plan",
			"__newname": name,
			"title": title,
			"billing_cycle": billing_cycle,
			"is_active": 1,
			"includes": includes,
		}
	).insert(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def get_plan_pricing(plan: str, currency: str | None = None, cluster: str | None = None) -> dict:
	"""Return the live catalog snapshot for a bundle.

	With a currency (and optional cluster) the applicable rate is resolved
	(most-specific region match, else global). Never cached as authoritative.
	"""
	doc = frappe.get_doc("Plan", plan)
	return doc.as_pricing(currency=currency, cluster=cluster)
