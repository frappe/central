# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Seed the non-VM product families on the ADR 0007 taxonomy (#77).

VM Plans landed with the masters in v15. This adds the three families the masters
were built for — AI Tokens, SaaS Storage, Frappe Box Remote Storage — plus the
resource types they bill on. Each is a Plan Category document; no schema change.

The billing spine is untouched: AI tokens "metered or bundled or both" is the
existing allowance+overage path with Resource Type = Tokens; Remote Storage is the
live-priced gauge (ADR 0002). IP and Snapshot stay valid *add-on* resource types
(an Add-on can bill on them) but are in no family's allowed_resource_types, so they
can never appear in a bundle's composition — which is exactly "not a core resource
type". v15 flagged zero IP/Snapshot composition rows, so there is nothing to migrate.

Idempotent: every seed is skipped when already present.
"""

import frappe

RESOURCE_TYPES = ["Tokens", "Storage", "Backup"]

CATEGORIES = [
	{
		"category_name": "AI Tokens",
		"configurator_builder": "simple",
		"sub_category_label": "",  # no variant axis by default
		"default_billing_type": "Metered",
		"default_pricing_mode": "Grandfathered",
		"billable_unit": "1M tokens",
		"meter_kind": "Counter",
		"description": "Token consumption — metered, and/or a bundled allowance with overage.",
		"allowed": ["Tokens"],
		"sub_categories": [],
	},
	{
		"category_name": "SaaS Storage",
		"configurator_builder": "simple",
		"sub_category_label": "",
		"default_billing_type": "Fixed",
		"default_pricing_mode": "Grandfathered",
		"billable_unit": "GB / mo",
		"meter_kind": "Gauge",
		"description": "Disk-only subscription for Frappe Suite sites (no vCPU/RAM exposed).",
		"allowed": ["Disk"],
		"sub_categories": [],
	},
	{
		"category_name": "Remote Storage",
		"configurator_builder": "simple",
		"sub_category_label": "Storage purpose",
		"default_billing_type": "Metered",
		"default_pricing_mode": "Live",
		"billable_unit": "GB-day",
		"meter_kind": "Gauge",
		"description": "Frappe Box remote storage — data, backups, or snapshots (live-priced).",
		"allowed": ["Storage", "Backup"],
		"sub_categories": ["Data", "Backups", "Snapshots"],
	},
]


def execute():
	_seed_resource_types()
	for spec in CATEGORIES:
		_seed_category(spec)


def _seed_resource_types():
	for name in RESOURCE_TYPES:
		if not frappe.db.exists("Resource Type", name):
			frappe.get_doc({"doctype": "Resource Type", "resource_type_name": name}).insert(
				ignore_permissions=True
			)


def _seed_category(spec):
	if not frappe.db.exists("Plan Category", spec["category_name"]):
		frappe.get_doc(
			{
				"doctype": "Plan Category",
				"category_name": spec["category_name"],
				"configurator_builder": spec["configurator_builder"],
				"sub_category_label": spec["sub_category_label"],
				"default_billing_type": spec["default_billing_type"],
				"default_pricing_mode": spec["default_pricing_mode"],
				"billable_unit": spec["billable_unit"],
				"meter_kind": spec["meter_kind"],
				"description": spec["description"],
				"allowed_resource_types": [{"resource_type": rt} for rt in spec["allowed"]],
			}
		).insert(ignore_permissions=True)
	for sub in spec["sub_categories"]:
		if not frappe.db.exists("Plan Sub-Category", sub):
			frappe.get_doc(
				{
					"doctype": "Plan Sub-Category",
					"sub_category_name": sub,
					"category": spec["category_name"],
				}
			).insert(ignore_permissions=True)
