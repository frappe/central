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
		# VM optimisation profiles carry the memory ratio (GB RAM per vCPU) the
		# configurator pins. Storage/Memory Optimised share 1:8; they differ by disk.
		"sub_categories": [
			{"name": "General", "memory_ratio": "1:4"},
			{"name": "CPU Optimised", "memory_ratio": "1:2"},
			{"name": "Memory Optimised", "memory_ratio": "1:8"},
			{"name": "Storage Optimised", "memory_ratio": "1:8"},
		],
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
			frappe.get_doc(
				{
					"doctype": "Plan Sub-Category",
					"sub_category_name": sub["name"],
					"category": spec["category_name"],
					"memory_ratio": sub.get("memory_ratio"),
				}
			).insert(ignore_permissions=True)
