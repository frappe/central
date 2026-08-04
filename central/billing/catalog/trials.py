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
	tier = frappe.db.get_value("Billing Profile", team, "trust_tier")
	return bool(tier) and tier == entry_tier()


def invoice_type_for(team: str) -> str:
	"""Every invoice is `billable`.

	The product no longer runs free trials — every team is billable and simply
	receives welcome credits, which the invoicing waterfall draws down first
	(settling small first bills to Paid with no card touched). The entry tier is
	just the lowest rung of the ladder now, not a trial, so it must NOT emit a
	Cost Report (that path never applies the welcome credits, stranding the team
	on an uncollectable Open invoice). `is_trial_team` and the Cost Report
	machinery are left dormant for a separate cleanup.
	"""
	return "Billable"


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

	from central.billing.catalog import entitlements

	# The cap is resolved live from the level × the team's currency, so conversion
	# just points the profile at the paid rung and pins it (manual_override).
	target = frappe.get_doc("Trust Tier Level", level)
	profile = entitlements._profile_for(team)
	profile.trust_tier_level = target.name
	profile.trust_tier = target.tier
	profile.manual_override = 1
	profile.promoted_at = frappe.utils.now_datetime()
	profile.promotion_basis = "converted to paid"
	profile.save(ignore_permissions=True)
	return entitlements._tier_result(team, profile)


def expire_trial(team: str, cluster_slices: dict | None = None) -> dict:
	"""Trial lapsed unconverted: emit a suspend directive on the token channel.

	Suspension is a Central-issued directive (next token = cap 0 + suspend flag),
	the same channel non-payment uses; the cluster stops then terminates per the
	staged enforcement (#14). Running resources are not touched here — the
	directive carries the intent.
	"""
	from central.billing.catalog.entitlements import issue_token
	from central.billing.platform import notifications

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
