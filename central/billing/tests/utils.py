# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Shared helpers for billing tests."""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.catalog.pricing import set_catalog_rates


class BillingTestCase(IntegrationTestCase):
	"""Atomic base for billing/server tests: it snapshots every tracked doctype
	before the test and deletes whatever the test added afterwards — so a test leaves
	the site exactly as it found it, EVEN when it commits (the concurrency/load tests,
	which the default per-test rollback can't undo, are the whole reason data leaks).

	The snapshot + sweep hang off `run()`, not setUp/tearDown, so a subclass gets this
	for free without having to remember a super() call — swap the base class and it's
	atomic. Deleting only rows absent from the pre-test snapshot means it can never
	touch data the test didn't create.
	"""

	# Top-level doctypes these tests create. Frappe links aren't DB foreign keys, so
	# raw deletes (frappe.db.delete) need no dependency ordering; child rows (e.g.
	# Team Member) are cleared via their parent below.
	_TRACKED = (
		"Payment Attempt", "Refund", "Credit Ledger Entry", "Credit Wallet",
		"Invoice", "Subscription Change", "Subscription", "Gateway Customer",
		"Entitlement Token", "Commitment", "Usage Rollup", "Payment Method",
		"Tax Profile", "Billing Profile", "Team Invitation", "Team Role",
		"Catalog Rate", "Plan", "Asset", "Team", "Atlas Instance", "Region", "User",
		"Webhook Event", "Notification Log",
	)

	def run(self, result=None):
		before = {doctype: set(frappe.get_all(doctype, pluck="name")) for doctype in self._TRACKED}
		try:
			return super().run(result)
		finally:
			self._sweep(before)

	def _sweep(self, before: dict) -> None:
		removed_teams: list[str] = []
		for doctype in self._TRACKED:
			added = list(set(frappe.get_all(doctype, pluck="name")) - before[doctype])
			if not added:
				continue
			if doctype == "Team":
				removed_teams = added
			frappe.db.delete(doctype, {"name": ["in", added]})
		if removed_teams:
			frappe.db.delete("Team Member", {"parenttype": "Team", "parent": ["in", removed_teams]})
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- persist the sweep past a test's own commit

# frappe.enqueue doesn't run inline in tests unless now=True, so patch it with this to
# execute an enqueued job synchronously — dropping the queue-control kwargs and calling
# the target with the real ones. Usage: patch("frappe.enqueue", side_effect=run_enqueued_inline).
_ENQUEUE_CONTROL_KWARGS = (
	"queue", "timeout", "enqueue_after_commit", "job_id", "at_front", "is_async", "now",
	"deduplicate", "event", "on_success", "on_failure", "job_name",
)


def run_enqueued_inline(method, **kwargs):
	for control in _ENQUEUE_CONTROL_KWARGS:
		kwargs.pop(control, None)
	if isinstance(method, str):  # enqueue takes a dotted path or a callable
		method = frappe.get_attr(method)
	return method(**kwargs)

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


def ensure_atlas_instance(region):
	"""The cluster a billing test bills against.

	Both Asset.cluster and Catalog Rate.cluster are required Links to Atlas Instance,
	so any test that creates a subscription or a per-region rate needs the instance
	(and its Region) to exist first."""
	from central.tests.utils import ensure_atlas_instance as _ensure_atlas_instance

	return _ensure_atlas_instance(region)


def make_plan(name, rates=None, includes=None, **kwargs):
	"""Create (or replace) a bundle Plan and its Catalog Rate rows; return its name."""
	if frappe.db.exists("Plan", name):
		frappe.delete_doc("Plan", name, force=True)

	doc = frappe.get_doc(
		{
			"doctype": "Plan",
			"title": kwargs.get("title", name),
			"category": kwargs.get("category", "VM Plans"),
			"sub_category": kwargs.get("sub_category"),
			"billing_cycle": kwargs.get("billing_cycle", "Monthly"),
			"is_active": kwargs.get("is_active", 1),
			"includes": includes if includes is not None else DEFAULT_INCLUDES,
		}
	)
	# Plan autonames by hash now; force a deterministic name for tests that reference
	# the plan by a known id (name_set skips autoname, unlike __newname under hash).
	doc.name = name
	doc.flags.name_set = True
	doc.insert(ignore_permissions=True)
	rates = rates if rates is not None else DEFAULT_RATES
	_ensure_rate_instances(rates)
	set_catalog_rates("Plan", doc.name, rates)
	return doc.name


def _ensure_rate_instances(rates):
	"""Seed the Atlas Instance behind every non-blank cluster a rate row references."""
	for cluster in {(r.get("cluster") or "").strip() for r in rates}:
		if cluster:
			ensure_atlas_instance(cluster)


def make_metered_plan(name, resource_type="Transfer", rates=None, pricing_mode="Grandfathered", **kwargs):
	"""Create (or replace) a metered single-resource Plan and its Catalog Rate rows.

	The ADR 0008 replacement for an Add-on: a single-resource Plan under a Metered
	Plan Category, which metering resolves by its resource type. The category is chosen
	by `pricing_mode` (Grandfathered vs Live). Drops any other active metered plan
	covering the same resource first, since at most one may be active. Returns its name."""
	category = "Live Metered Resources" if pricing_mode == "Live" else "Metered Resources"
	_clear_metered_plans(resource_type, keep=name)
	if frappe.db.exists("Plan", name):
		frappe.delete_doc("Plan", name, force=True)

	doc = frappe.get_doc(
		{
			"doctype": "Plan",
			"title": kwargs.get("title", name),
			"category": category,
			"billing_cycle": "Monthly",
			"is_active": kwargs.get("is_active", 1),
			"includes": [
				{
					"resource_type": resource_type,
					"quantity": kwargs.get("quantity", 0),
					"unit": kwargs.get("unit", "GB"),
				}
			],
		}
	)
	# Plan autonames by hash; force a deterministic name for tests that reference it.
	doc.name = name
	doc.flags.name_set = True
	doc.insert(ignore_permissions=True)
	rates = rates if rates is not None else DEFAULT_ADDON_RATES
	_ensure_rate_instances(rates)
	set_catalog_rates("Plan", doc.name, rates)
	return doc.name


def _clear_metered_plans(resource_type, keep=None):
	"""Delete every active/inactive metered single-resource Plan for `resource_type`
	(except `keep`), so a test can re-seed without tripping the one-active-per-resource
	uniqueness rule on data committed by an earlier test."""
	metered_cats = frappe.get_all("Plan Category", filters={"billing_type": "Metered"}, pluck="name")
	for plan in frappe.get_all("Plan", filters={"category": ["in", metered_cats]}, pluck="name"):
		if plan == keep:
			continue
		includes = frappe.get_all("Plan Includes", filters={"parent": plan}, pluck="resource_type")
		if len(includes) == 1 and includes[0] == resource_type:
			frappe.delete_doc("Plan", plan, force=True)


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


def purge_teams(teams):
	"""Delete the given teams and every row that links them, for test teardown.

	Tests that `frappe.db.commit()` (load/concurrency runs) escape the per-test
	rollback, so anything they created — the Team plus its billing artifacts
	(subscriptions, invoices, profiles, wallets, gateway customers, …) — leaks into
	the site. Raw DELETEs across every `team`-linked table (discovered live) clear it
	without tripping Link-integrity ordering, since Frappe links aren't DB FKs."""
	teams = [t for t in teams if frappe.db.exists("Team", t)]
	if not teams:
		return
	# Every doctype with a `team` Link column — discovered live so nothing is missed.
	tables = frappe.db.sql_list(
		"""SELECT DISTINCT TABLE_NAME FROM information_schema.COLUMNS
		   WHERE TABLE_SCHEMA = DATABASE() AND COLUMN_NAME = 'team' AND TABLE_NAME LIKE 'tab%%'"""
	)
	for table in tables:
		doctype = table[len("tab") :]
		if doctype != "Team":
			frappe.db.delete(doctype, {"team": ["in", teams]})
	frappe.db.delete("Team Member", {"parenttype": "Team", "parent": ["in", teams]})
	frappe.db.delete("Team", {"name": ["in", teams]})


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


def make_billing_subscription(team, cluster, plan, start_date=None, clear_changes=True, **kwargs):
	"""Provision a billable subscription for billing tests under the Asset model:
	ensure the cluster's Atlas Instance + the team's Billing Profile currency, create
	the Asset (carrying the region) + linked Subscription, and (by default) clear the
	auto 'Created' segment so the test can author its own Subscription Change timeline
	with `add_segment`. Returns the Subscription name."""
	from central.billing.catalog import subscriptions

	ensure_atlas_instance(cluster)
	ensure_team(team)
	currency = kwargs.pop("currency", "INR")
	if not frappe.db.get_value("Billing Profile", team, "currency"):
		complete_billing_profile(team, currency=currency)
	sub = subscriptions.create_subscription(
		team=team, cluster=cluster, plan=plan, start_date=start_date, **kwargs
	)
	if clear_changes:
		frappe.db.delete("Subscription Change", {"subscription": sub.name})
	return sub.name


def seed_running_resource(team, resource_id, cluster, plan, rate=1000, currency="INR",
						  effective_at="2026-06-01 00:00:00"):
	"""Seed a provisioned, running resource on the Subscription Change ledger (ADR 0010):
	its Asset (named by `resource_id`) + Subscription + an open `Created` segment at
	`rate`/`currency`. The ledger replacement for the retired price-lock event seeding
	(#86) — metering and every 'what is running' reader resolve the resource through this
	open segment. Returns the Subscription name."""
	sub = make_billing_subscription(team, cluster, plan, resource_id=resource_id, currency=currency)
	add_segment(sub, "Created", rate, effective_at, plan=plan, currency=currency)
	return sub


def add_segment(subscription, change_type, rate, effective_at, plan=None, currency="INR"):
	"""Author one Subscription Change run-segment directly — the unit billing
	day-weights over in the new model. `change_type` is Created / Plan Changed /
	Cancelled; a Cancelled marker carries no rate (it just closes the prior segment)."""
	return frappe.get_doc(
		{
			"doctype": "Subscription Change",
			"subscription": subscription,
			"change_type": change_type,
			"new_value": plan,
			"locked_rate": None if change_type == "Cancelled" else rate,
			"currency": currency,
			"effective_at": effective_at,
		}
	).insert(ignore_permissions=True)


def set_team_tier(team, level="t1", max_spend=None, manual_override=1):
	"""Pin a team's trust tier on its Billing Profile — the per-team tier carrier
	since the standalone Trust Tier doctype was folded in (#62). Ensures a profile
	exists; an explicit `max_spend` is stored as a bespoke `override_max_spend` so
	get_team_caps returns exactly it regardless of the level's currency thresholds."""
	if not frappe.db.exists("Billing Profile", team):
		frappe.get_doc(
			{"doctype": "Billing Profile", "team": team, "currency": "INR"}
		).insert(ignore_permissions=True)
	values = {
		"trust_tier_level": level,
		"trust_tier": level,
		"manual_override": manual_override,
	}
	if max_spend is not None:
		values["override_max_spend"] = max_spend
	frappe.db.set_value("Billing Profile", team, values)
	return team


def clear_team_tier(team):
	"""Reset a team's tier fields on its Billing Profile (test teardown)."""
	if frappe.db.exists("Billing Profile", team):
		frappe.db.set_value(
			"Billing Profile",
			team,
			{
				"trust_tier_level": None,
				"trust_tier": None,
				"manual_override": 0,
				"override_max_spend": 0,
				"promoted_at": None,
				"promotion_basis": None,
			},
		)


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
