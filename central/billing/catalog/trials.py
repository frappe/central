# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Free/trial as the entry trust tier (issue #16).

Free/trial is not a separate code path: provisioning, the event log, metering,
the price-lock and the line-item math all run identically to a paying team.
Central branches at exactly one point — at invoice generation an entry-tier
team's invoice is emitted as `cost_report` (computed, never charged), so the
free/trial subsidy is a *true* cost.

Conversion flips the tier (cost_report -> billable) with resources untouched;
expiry reuses the suspend directive on the entitlement-token channel.
"""

import frappe


def entry_tier() -> str | None:
	"""The entry/trial rung of the ladder: the default level, else lowest sequence."""
	default = frappe.get_all("Trust Tier Level", filters={"is_default": 1}, pluck="tier")
	if default:
		return default[0]
	lowest = frappe.get_all("Trust Tier Level", fields=["tier"], order_by="sequence asc", limit=1)
	return lowest[0].tier if lowest else None


def is_trial_team(team: str) -> bool:
	"""A team sitting on the entry tier is on free/trial."""
	tier = frappe.db.get_value("Trust Tier", team, "tier")
	return bool(tier) and tier == entry_tier()


def invoice_type_for(team: str) -> str:
	"""`cost_report` for entry-tier teams, `billable` otherwise."""
	return "Cost Report" if is_trial_team(team) else "Billable"


def convert_to_paid(team: str, level: str | None = None):
	"""Flip a trial team to a paid tier. Resources keep running (no suspend).

	`level` is a Trust Tier Level name; defaults to the lowest non-entry rung.
	The upgrade is marked manual_override so it sticks (a deliberate conversion,
	not an auto-ramp). Subsequent invoices are `billable`.
	"""
	if not level:
		paid = frappe.get_all(
			"Trust Tier Level",
			filters={"is_default": 0},
			fields=["name"],
			order_by="sequence asc",
			limit=1,
		)
		if not paid:
			frappe.throw("No paid tier level configured to convert into.", frappe.ValidationError)
		level = paid[0].name

	target = frappe.get_doc("Trust Tier Level", level)
	tier = (
		frappe.get_doc("Trust Tier", team)
		if frappe.db.exists("Trust Tier", team)
		else frappe.get_doc({"doctype": "Trust Tier", "team": team})
	)
	tier.update(
		{
			"level": target.name,
			"tier": target.tier,
			"max_spend": target.max_spend,
			"max_resource_count": target.max_resource_count,
			"allowed_plans": target.allowed_plans,
			"allowed_clusters": target.allowed_clusters,
			"allowed_resource_types": target.allowed_resource_types,
			"manual_override": 1,
			"promoted_at": frappe.utils.now_datetime(),
			"promotion_basis": "converted to paid",
		}
	)
	tier.save(ignore_permissions=True)
	return tier


def expire_trial(team: str, cluster_slices: dict | None = None) -> dict:
	"""Trial lapsed unconverted: emit a suspend directive on the token channel.

	Suspension is a Central-issued directive (next token = cap 0 + suspend flag),
	the same channel non-payment uses; the cluster stops then terminates per the
	staged enforcement (#14). Running resources are not touched here — the
	directive carries the intent.
	"""
	from central.billing.platform import notifications
	from central.billing.catalog.entitlements import issue_token

	notifications.notify(team, "Trial Expiring", context={})
	return issue_token(team, cluster_slices or {}, suspend=True)


def subsidy_total(from_date=None, to_date=None) -> float:
	"""Total free/trial subsidy = sum of cost_report invoice subtotals in range.

	The true cost-to-company of non-paying teams; surfaced on the admin
	dashboard (#19).
	"""
	filters = [["invoice_type", "=", "Cost Report"]]
	if from_date:
		filters.append(["period_start", ">=", from_date])
	if to_date:
		filters.append(["period_end", "<=", to_date])
	return frappe.utils.flt(sum(frappe.get_all("Invoice", filters=filters, pluck="subtotal")))
