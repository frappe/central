# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Seed a starter VM Plan ladder so a fresh install ships a priced catalog.

The taxonomy masters (categories / resource types) and the component rate card are
seeded elsewhere (taxonomy_setup / rate_card); this adds the preset flat-rate VM
bundles a team can actually provision on day one — the Starter → Enterprise ladder
under the `VM Plans` family, each carrying a global (blank-cluster) rate per shipped
currency. Rates are cluster-agnostic so they resolve on an install with no
regions configured yet; an admin re-prices per region afterwards.

Idempotent: a plan is created only when its slug is absent, and each rate is upserted
only when missing, so re-running (after_install / after_migrate) never clobbers an
admin's edit.
"""

import frappe

from central.billing.catalog.pricing import get_catalog_rates, set_catalog_rate

VM_CATEGORY = "VM Plans"
VM_SUB_CATEGORY = "General"

# (slug, title, vcpu, ram_gb, disk_gb, transfer_gb, {currency: monthly rate}).
# Round numbers per currency (not FX-derived at runtime) — admins tune per region.
# We bill only in INR and USD for now, so each plan ships those two rates.
STARTER_PLANS = [
	("plan-1vcpu", "Starter · 1 vCPU / 2 GB", 1, 2, 25, 100, {"INR": 1500, "USD": 18}),
	("plan-2vcpu", "Basic · 2 vCPU / 4 GB", 2, 4, 50, 200, {"INR": 3000, "USD": 36}),
	("plan-4vcpu", "Standard · 4 vCPU / 8 GB", 4, 8, 100, 400, {"INR": 6000, "USD": 72}),
	("plan-8vcpu", "Pro · 8 vCPU / 16 GB", 8, 16, 200, 800, {"INR": 12000, "USD": 145}),
	("plan-16vcpu", "Enterprise · 16 vCPU / 32 GB", 16, 32, 400, 1600, {"INR": 24000, "USD": 289}),
]


def ensure_starter_plans():
	"""Seed the starter VM Plan ladder + its rates if absent. Safe to call repeatedly."""
	# The plans live under VM Plans; without that master (seeded by taxonomy_setup)
	# a Plan can't be saved, so there is nothing to seed yet.
	if not frappe.db.exists("Plan Category", VM_CATEGORY):
		return

	sub_category = VM_SUB_CATEGORY if frappe.db.exists("Plan Sub-Category", VM_SUB_CATEGORY) else None
	for slug, title, vcpu, ram, disk, transfer, rates in STARTER_PLANS:
		_ensure_plan(slug, title, vcpu, ram, disk, transfer, sub_category)
		_ensure_rates(slug, rates)


def _ensure_plan(slug, title, vcpu, ram, disk, transfer, sub_category):
	if frappe.db.exists("Plan", slug):
		return
	doc = frappe.get_doc(
		{
			"doctype": "Plan",
			"title": title,
			"category": VM_CATEGORY,
			"sub_category": sub_category,
			"billing_cycle": "Monthly",
			"is_active": 1,
			"includes": [
				{"resource_type": "Compute", "quantity": vcpu, "unit": "vCPU"},
				{"resource_type": "Memory", "quantity": ram, "unit": "GB"},
				{"resource_type": "Disk", "quantity": disk, "unit": "GB"},
				{"resource_type": "Transfer", "quantity": transfer, "unit": "GB"},
			],
		}
	)
	# Plan autonames by hash; pin the readable slug so the seed is idempotent on it
	# and Catalog Rate's priced_for link is stable/legible.
	doc.name = slug
	doc.flags.name_set = True
	doc.insert(ignore_permissions=True)


def _ensure_rates(slug, rates):
	"""Upsert the plan's global (blank-cluster) rate for each shipped currency,
	leaving any currency an admin has already priced (and any regional row) untouched.

	set_catalog_rate is a per-(currency, cluster) upsert — unlike set_catalog_rates,
	which replaces every row for the plan — so seeding one currency never disturbs
	another cluster's rate."""
	priced = {r.currency for r in get_catalog_rates("Plan", slug) if not r.cluster}
	for currency, rate in rates.items():
		if currency not in priced:
			set_catalog_rate("Plan", slug, currency, rate)


AI_PLAN = "ai-usage"
AI_CATEGORY = "AI Tokens"
AI_RESOURCE_TYPE = "AI Usage"

PUBLIC_IPV4_PLAN = "public-ipv4"
PUBLIC_IPV4_CATEGORY = "Live Metered Resources"
IP_RESOURCE_TYPE = "IP"
# One public IPv4 address per month. IPv6 is free, so it has no rate.
STARTER_PUBLIC_IPV4_RATES = {"INR": 170, "USD": 2}


def ensure_ai_plan() -> None:
	"""Seed the plan every AI team is subscribed to. Safe to call repeatedly."""
	# AI is billed at Grove's cost, converted at the month's rate, so the catalog rate stays 0.
	if frappe.db.exists("Plan", AI_PLAN) or not frappe.db.exists("Plan Category", AI_CATEGORY):
		return
	_insert_metered_plan(AI_PLAN, "AI Usage", AI_CATEGORY, AI_RESOURCE_TYPE)
	_ensure_rates(AI_PLAN, {"INR": 0, "USD": 0})


def ensure_public_ipv4_plan() -> None:
	"""Seed the plan that prices a public IPv4 per address-month. Safe to call repeatedly."""
	from central.billing.revenue.metering import metered_plan_for

	if not frappe.db.exists("Plan Category", PUBLIC_IPV4_CATEGORY) or metered_plan_for(IP_RESOURCE_TYPE):
		return
	_insert_metered_plan(PUBLIC_IPV4_PLAN, "Public IPv4", PUBLIC_IPV4_CATEGORY, IP_RESOURCE_TYPE)
	# The prices an operator set on the IP rate card, regional ones too, carry over.
	for row in get_catalog_rates("Resource Type", IP_RESOURCE_TYPE):
		set_catalog_rate("Plan", PUBLIC_IPV4_PLAN, row.currency, row.rate, cluster=row.cluster)
	_ensure_rates(PUBLIC_IPV4_PLAN, STARTER_PUBLIC_IPV4_RATES)


def _insert_metered_plan(name: str, title: str, category: str, resource_type: str) -> None:
	doc = frappe.get_doc(
		{
			"doctype": "Plan",
			"title": title,
			"category": category,
			"billing_cycle": "Monthly",
			"is_active": 1,
			"includes": [{"resource_type": resource_type, "quantity": 0, "unit": "Nos"}],
		}
	)
	# A readable name keeps the seed idempotent and its Catalog Rates legible.
	doc.name = name
	doc.flags.name_set = True
	# Seeded by install and migrate, which run with no user.
	doc.insert(ignore_permissions=True)
