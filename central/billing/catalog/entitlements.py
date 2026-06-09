# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Trust tiers — the entitlement cap, computed by Central from billing history.

Two measures, never conflated: promotion here uses *historical paid* (Central,
monthly); the cluster's provisioning check uses *projected run-rate* (live).
This module owns only the historical/promotion side.
"""

import frappe

from central.billing.catalog.signing import sign_payload

_LEVEL_FIELDS = (
	"name",
	"tier",
	"sequence",
	"is_default",
	"max_spend",
	"max_resource_count",
	"allowed_plans",
	"allowed_clusters",
	"allowed_resource_types",
	"min_paid_invoices",
	"min_cumulative_paid",
)


def get_ladder():
	"""Admin-defined ladder rungs, ordered low → high."""
	return frappe.get_all(
		"Trust Tier Level", fields=list(_LEVEL_FIELDS), order_by="sequence asc"
	)


def evaluate_tier(paid_invoice_count: int, cumulative_paid, levels):
	"""Highest rung whose thresholds the team's paid history meets.

	A rung qualifies only when BOTH thresholds are met. With no qualifying rung,
	the entry tier (lowest sequence) applies.
	"""
	qualifying = [
		level
		for level in levels
		if paid_invoice_count >= (level.min_paid_invoices or 0)
		and cumulative_paid >= (level.min_cumulative_paid or 0)
	]
	if not qualifying:
		return min(levels, key=lambda level: level.sequence) if levels else None
	return max(qualifying, key=lambda level: level.sequence)


def recompute_trust_tier(team: str, paid_invoice_count: int, cumulative_paid):
	"""Promote/demote a team from historical paid. Manual overrides are exempt.

	Demotion lowers the cap only — it never stops running resources (that is a
	non-payment suspend directive on the token, not a tier change).
	"""
	target = evaluate_tier(paid_invoice_count, cumulative_paid, get_ladder())

	if frappe.db.exists("Trust Tier", team):
		tier = frappe.get_doc("Trust Tier", team)
	else:
		tier = frappe.get_doc({"doctype": "Trust Tier", "team": team})

	if tier.manual_override:
		return tier

	promoted = (tier.tier or "") != target.tier
	tier.update(
		{
			"level": target.name,
			"tier": target.tier,
			"max_spend": target.max_spend,
			"max_resource_count": target.max_resource_count,
			"allowed_plans": target.allowed_plans,
			"allowed_clusters": target.allowed_clusters,
			"allowed_resource_types": target.allowed_resource_types,
		}
	)
	if promoted:
		tier.promoted_at = frappe.utils.now_datetime()
		tier.promotion_basis = (
			f"{paid_invoice_count} paid invoices + cumulative {cumulative_paid} → {target.tier}"
		)

	tier.save(ignore_permissions=True)

	# Mandate ceilings are tied to the cap; a raised cap needs customer re-consent
	# (the team is held at the old ceiling until re-authorisation). #08
	from central.billing.payments import mandates

	mandates.reconcile_mandates_to_cap(team)
	return tier


def issue_token(
	team: str,
	cluster_slices: dict,
	lifetime_hours: int = 24,
	suspend: bool = False,
	terminate: bool = False,
):
	"""Issue a signed, short-lived entitlement token for a team.

	cluster_slices is `{cluster: {max_spend, max_resource_count}}`; the per-cluster
	slices are pre-partitioned so their sum never exceeds the team's cap — a
	cap enforced independently per cluster is not a per-team cap otherwise.
	"""
	tier = frappe.get_doc("Trust Tier", team)

	sliced_spend = sum((s.get("max_spend") or 0) for s in cluster_slices.values())
	if sliced_spend > (tier.max_spend or 0):
		frappe.throw(
			f"Cluster slices sum ({sliced_spend}) exceed team cap ({tier.max_spend})",
			frappe.ValidationError,
		)

	issued_at = frappe.utils.now_datetime()
	expires_at = frappe.utils.add_to_date(issued_at, hours=lifetime_hours)

	payload = {
		"team": team,
		"cluster_slices": cluster_slices,
		"allowed_plans": tier.allowed_plans or [],
		"allowed_resource_types": tier.allowed_resource_types or [],
		"suspend": 1 if suspend else 0,
		"terminate": 1 if terminate else 0,
		"issued_at": issued_at.isoformat(),
		"expires_at": expires_at.isoformat(),
	}
	signature = sign_payload(payload)

	doc = frappe.get_doc(
		{
			"doctype": "Entitlement Token",
			"team": team,
			"cluster_slices": frappe.as_json(cluster_slices),
			"allowed_plans": frappe.as_json(payload["allowed_plans"]),
			"allowed_resource_types": frappe.as_json(payload["allowed_resource_types"]),
			"suspend": payload["suspend"],
			"terminate": payload["terminate"],
			"issued_at": issued_at,
			"expires_at": expires_at,
			"signature": signature,
		}
	).insert(ignore_permissions=True)

	return {"name": doc.name, "payload": payload, "signature": signature}
