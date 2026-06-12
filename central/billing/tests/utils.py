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
	{"resource_type": "Compute", "quantity": 2, "unit": "vCPU"},
	{"resource_type": "Memory", "quantity": 4, "unit": "GB"},
	{"resource_type": "Disk", "quantity": 80, "unit": "GB"},
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
			"billing_cycle": kwargs.get("billing_cycle", "Monthly"),
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
			"resource_type": kwargs.get("resource_type", "Transfer"),
			"unit": kwargs.get("unit", "GB"),
			"billing_type": kwargs.get("billing_type", "Metered"),
			"billing_interval": kwargs.get("billing_interval", "Monthly"),
			"pricing_mode": kwargs.get("pricing_mode", "Grandfathered"),
		}
	)
	doc.insert(ignore_permissions=True)
	set_catalog_rates("Add-on", doc.name, rates if rates is not None else DEFAULT_ADDON_RATES)
	return doc.name


def make_user(email=None):
	"""Create (or reuse) a plain user with no platform roles — stands in for a
	customer or the role-less Agent key."""
	email = email or f"cust-{frappe.generate_hash(6)}@example.com"
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Cust", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	return email


def ensure_team(slug, owner=None):
	"""Ensure a Central `Team` whose `name` *is* `slug` exists, bypassing the
	`TEAM-#####` series via `flags.name_set`.

	`team` is now a `Link → Team` (#43), so tests can no longer insert a billing
	doc with a free-text slug. Forcing the Team's name to the slug keeps the
	readable identifier valid as a link with no churn to the test bodies.
	Idempotent; returns `slug`."""
	if frappe.db.exists("Team", slug):
		return slug
	# One shared owner across all ensure_team() teams — a fresh user per team
	# would trip Frappe's user-creation throttle in the load test (hundreds of
	# teams). Owning many teams is fine; these teams exist only to satisfy the link.
	owner = owner or make_user("billing-test-team-owner@example.com")
	doc = frappe.get_doc({"doctype": "Team", "team_name": slug, "owner_user": owner})
	doc.flags.name_set = True
	doc.name = slug
	doc.insert(ignore_permissions=True)
	return slug


def complete_billing_profile(team, currency="INR"):
	"""A minimal *complete* Billing Profile (currency + legal name + address) so the
	money-movement gate (_require_billing_setup) passes. Saves the doc directly,
	bypassing the API's gateway-supported-currency check, so it works regardless of
	which gateways a given test has configured."""
	values = {
		"doctype": "Billing Profile", "team": team, "currency": currency,
		"legal_name": f"{team} Ltd", "email": "billing@test.example", "phone": "9999999999",
		"address_line1": "1 Test Street", "city": "Pune",
		"state": "Maharashtra", "country": "India", "pincode": "411001",
	}
	if frappe.db.exists("Billing Profile", team):
		doc = frappe.get_doc("Billing Profile", team)
		doc.update(values)
	else:
		doc = frappe.get_doc(values)
	doc.save(ignore_permissions=True)
	return team


def make_billing_team(user, role="Billing", team_name=None):
	"""A Central `Team` with `user` as an active member under `role`. The team's
	Owner is a separate throwaway user (a Team must have exactly one Owner), so
	`user` carries exactly `role`'s capabilities — `Billing`/`Owner` grant
	`billing:view` + `billing:manage`; `Viewer`/`Developer` grant neither.
	Returns the Team doc; `team.name` is the slug to pass to the billing APIs."""
	owner = make_user(f"owner-{frappe.generate_hash(6)}@example.com")
	return frappe.get_doc(
		{
			"doctype": "Team",
			"team_name": team_name or f"Billing {frappe.generate_hash(5)}",
			"owner_user": owner,
			"members": [{"user": user, "role": role, "status": "Active"}],
		}
	).insert(ignore_permissions=True)


def make_custom_role_team(user, capabilities, team_name=None):
	"""A Central `Team` whose `user` member carries a *custom* (non-system) Team
	Role granting exactly `capabilities` — for capability combinations the stock
	system roles don't offer (notably `billing:view` WITHOUT `billing:manage`,
	which no system role has). The Owner is a separate throwaway user so `user`
	holds only the custom grant. Returns the Team doc."""
	owner = make_user(f"owner-{frappe.generate_hash(6)}@example.com")
	team = frappe.get_doc(
		{
			"doctype": "Team",
			"team_name": team_name or f"Custom {frappe.generate_hash(5)}",
			"owner_user": owner,
		}
	).insert(ignore_permissions=True)
	# A custom Team Role must be tied to exactly one team (its scope).
	role = frappe.get_doc(
		{
			"doctype": "Team Role",
			"role_name": f"Custom {frappe.generate_hash(5)}",
			"is_system": 0,
			"team": team.name,
			"capabilities": [{"capability": c} for c in capabilities],
		}
	).insert(ignore_permissions=True)
	team.append("members", {"user": user, "role": role.name, "status": "Active"})
	team.save(ignore_permissions=True)
	return team
