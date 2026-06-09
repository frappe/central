# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Shared helpers for billing tests."""

import frappe

from central.billing.catalog.pricing import set_catalog_rates

DEFAULT_RATES = [
	{"cluster": "", "currency": "USD", "rate": 40},
	{"cluster": "", "currency": "INR", "rate": 3200},
]

DEFAULT_ADDON_RATES = [
	{"cluster": "", "currency": "USD", "rate": 0.01},
	{"cluster": "", "currency": "INR", "rate": 0.8},
]

DEFAULT_INCLUDES = [
	{"resource_type": "compute", "quantity": 2, "unit": "vCPU"},
	{"resource_type": "memory", "quantity": 4, "unit": "GB"},
	{"resource_type": "disk", "quantity": 80, "unit": "GB"},
]


def make_plan(name, rates=None, includes=None, **kwargs):
	"""Create (or replace) a bundle Plan and its Catalog Rate rows; return its name."""
	if frappe.db.exists("Plan", name):
		frappe.delete_doc("Plan", name, force=True)

	doc = frappe.get_doc(
		{
			"doctype": "Plan",
			"__newname": name,
			"title": kwargs.get("title", name),
			"billing_cycle": kwargs.get("billing_cycle", "monthly"),
			"is_active": kwargs.get("is_active", 1),
			"includes": includes if includes is not None else DEFAULT_INCLUDES,
		}
	)
	doc.insert(ignore_permissions=True)
	set_catalog_rates("Plan", doc.name, rates if rates is not None else DEFAULT_RATES)
	return doc.name


def make_addon(name, rates=None, **kwargs):
	"""Create (or replace) an Add-on and its Catalog Rate rows; return its name."""
	if frappe.db.exists("Add-on", name):
		frappe.delete_doc("Add-on", name, force=True)

	doc = frappe.get_doc(
		{
			"doctype": "Add-on",
			"__newname": name,
			"title": kwargs.get("title", name),
			"resource_type": kwargs.get("resource_type", "transfer"),
			"unit": kwargs.get("unit", "GB"),
			"billing_type": kwargs.get("billing_type", "metered"),
			"billing_interval": kwargs.get("billing_interval", "monthly"),
			"pricing_mode": kwargs.get("pricing_mode", "grandfathered"),
		}
	)
	doc.insert(ignore_permissions=True)
	set_catalog_rates("Add-on", doc.name, rates if rates is not None else DEFAULT_ADDON_RATES)
	return doc.name
