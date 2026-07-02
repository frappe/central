# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Idempotent seed of the catalog taxonomy masters (ADR 0007).

The Plan Category / Plan Sub-Category / Resource Type masters are reference data the
whole catalog depends on (a Plan can't be saved without a real `category` and
`resource_type` links). They must exist on a *fresh* install too — and Frappe skips
migration patches on fresh installs, so the seed can't live only in v15/v16. This is
the single source of truth, called from `after_install`, `after_migrate`, and
`before_tests` (hooks) as well as the patches.

Idempotent: every row is created only when absent, so it is safe to run repeatedly.
"""

import frappe

# Every value the catalog's `resource_type` links can hold. IP and Snapshot are valid
# metered-resource dimensions but appear in no fixed category's allowed list (so never
# bundle composition).
RESOURCE_TYPES = ["Compute", "Memory", "Disk", "Transfer", "IP", "Snapshot", "Tokens", "Storage", "Backup"]

# The vCPU ladder a composed-config slider snaps to — the configurator's choices,
# fractional vCPUs through powers of two (final-plan-pricing.md §4).
VCPU_LADDER = "0.125,0.25,0.5,1,2,4,8,16,32,64,128,256"

# Metered categories host the single-resource overage meters that used to be Add-ons
# (ADR 0008). A metered single-resource Plan under one of these is what metering.py
# resolves by resource type; the family carries the billing behaviour (interval +
# Grandfathered/Live). The allow-list is left blank (unconstrained) so any overage
# resource type can attach.
CATEGORIES = [
	{
		"category_name": "VM Plans",
		"configurator_builder": "VM Rungs",
		"provision_target": "Server",
		"sub_category_label": "Optimization profile",
		"description": "Flat-rate compute bundles (vCPU + memory + disk + transfer).",
		"billing_type": "Fixed",
		"allowed": ["Compute", "Memory", "Disk", "Transfer"],
		# VM optimisation profiles carry the composed-config bounds (ADR 0009): the RAM
		# ratio (GB per vCPU), the allowed vCPU steps, and the disk range the slider is
		# bounded to. Storage/Memory Optimised share ratio 8; they differ by disk.
		# vCPU follows the configurator ladder (fractional vCPUs through powers of two)
		# so a slider can reach a 1/8 vCPU micro config; RAM derives from the ratio.
		"sub_categories": [
			{"name": "General", "ram_ratio": 4, "vcpu_steps": VCPU_LADDER, "disk_min": 10, "disk_max": 2000},
			{"name": "CPU Optimised", "ram_ratio": 2, "vcpu_steps": VCPU_LADDER, "disk_min": 10, "disk_max": 1000},
			{"name": "Memory Optimised", "ram_ratio": 8, "vcpu_steps": VCPU_LADDER, "disk_min": 10, "disk_max": 2000},
			{"name": "Storage Optimised", "ram_ratio": 8, "vcpu_steps": VCPU_LADDER, "disk_min": 100, "disk_max": 10000},
		],
	},
	{
		# The per-unit rates that compose a custom VM config (ADR 0009/0011). Its
		# provision_target 'Resource' switches the Configurator to authoring Resource
		# Rates (Compute / Memory / Disk priced per unit) instead of a plan ladder — no
		# Plans live here; it is the pricing home for composed configs.
		"category_name": "VM Resources",
		"configurator_builder": "Simple",
		"provision_target": "Resource",
		"sub_category_label": "",
		"description": "Per-unit resource rates (Compute / Memory / Disk) a custom VM config is composed and billed from.",
		"billing_type": "Fixed",
		"allowed": ["Compute", "Memory", "Disk"],
		"sub_categories": [],
	},
	{
		"category_name": "AI Tokens",
		"configurator_builder": "Simple",
		"sub_category_label": "",
		"description": "Token consumption — metered, and/or a bundled allowance with overage.",
		"allowed": ["Tokens"],
		"sub_categories": [],
	},
	{
		"category_name": "SaaS Storage",
		"configurator_builder": "Simple",
		"sub_category_label": "",
		"description": "Disk-only subscription for Frappe Suite sites (no vCPU/RAM exposed).",
		"allowed": ["Disk"],
		"sub_categories": [],
	},
	{
		"category_name": "Remote Storage",
		"configurator_builder": "Simple",
		"sub_category_label": "Storage purpose",
		"description": "Frappe Box remote storage — data, backups, or snapshots (live-priced).",
		"allowed": ["Storage", "Backup"],
		"sub_categories": [{"name": "Data"}, {"name": "Backups"}, {"name": "Snapshots"}],
	},
	{
		"category_name": "Metered Resources",
		"configurator_builder": "Simple",
		"sub_category_label": "",
		"description": "Per-unit overage meters (transfer, IPs, token overage). The rate is locked at provision, like a bundle (ADR 0008).",
		"billing_type": "Metered",
		"billing_interval": "Monthly",
		"pricing_mode": "Grandfathered",
		"allowed": [],
		"sub_categories": [],
	},
	{
		"category_name": "Live Metered Resources",
		"configurator_builder": "Simple",
		"sub_category_label": "",
		"description": "Live-priced per-unit meters for depreciating storage (e.g. snapshots) — the rate is read from the current Catalog Rate each period, never locked (ADR 0002 / 0008).",
		"billing_type": "Metered",
		"billing_interval": "Monthly",
		"pricing_mode": "Live",
		"allowed": [],
		"sub_categories": [],
	},
]


def ensure_catalog_masters():
	"""Seed the taxonomy masters if absent. Safe to call repeatedly."""
	for name in RESOURCE_TYPES:
		if not frappe.db.exists("Resource Type", name):
			frappe.get_doc({"doctype": "Resource Type", "resource_type_name": name}).insert(
				ignore_permissions=True
			)
	for spec in CATEGORIES:
		_ensure_category(spec)

	# The composed-config component rate card prices the Resource Types just seeded
	# (ADR 0009); seed it here so a fresh install can price a custom config too.
	from central.billing.catalog.rate_card import ensure_component_rate_card

	ensure_component_rate_card()


def _ensure_category(spec):
	if not frappe.db.exists("Plan Category", spec["category_name"]):
		frappe.get_doc(
			{
				"doctype": "Plan Category",
				"category_name": spec["category_name"],
				"configurator_builder": spec["configurator_builder"],
				"provision_target": spec.get("provision_target", ""),
				"sub_category_label": spec["sub_category_label"],
				"description": spec["description"],
				"billing_type": spec.get("billing_type", "Fixed"),
				"billing_interval": spec.get("billing_interval", ""),
				"pricing_mode": spec.get("pricing_mode", ""),
				"allowed_resource_types": [{"resource_type": rt} for rt in spec["allowed"]],
			}
		).insert(ignore_permissions=True)
	for sub in spec["sub_categories"]:
		if not frappe.db.exists("Plan Sub-Category", sub["name"]):
			ram_ratio = sub.get("ram_ratio")
			frappe.get_doc(
				{
					"doctype": "Plan Sub-Category",
					"sub_category_name": sub["name"],
					"category": spec["category_name"],
					"ram_ratio": ram_ratio,
					"vcpu_steps": sub.get("vcpu_steps"),
					"disk_min": sub.get("disk_min"),
					"disk_max": sub.get("disk_max"),
					# Legacy 1:N mirror of the authoritative numeric ram_ratio.
					"memory_ratio": f"1:{ram_ratio}" if ram_ratio else None,
				}
			).insert(ignore_permissions=True)
