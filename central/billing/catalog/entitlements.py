# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Trust tiers — the entitlement cap, computed by Central from billing history.

Two measures, never conflated: promotion here uses *historical paid* (Central,
monthly); the cluster's provisioning check uses *projected run-rate* (live).
This module owns only the historical/promotion side.
"""

import frappe

from central.billing.catalog.signing import sign_payload

# Currency-independent rung fields (money limits live per-currency on the
# Thresholds child table — see threshold_for()).
_LEVEL_FIELDS = (
	"name",
	"tier",
	"sequence",
	"is_default",
	"max_resource_count",
	"allowed_plans",
	"allowed_clusters",
	"allowed_resource_types",
	"min_paid_invoices",
)


def team_currency(team: str) -> str:
	"""The currency a team's caps are denominated in.

	Sourced from the Billing Profile (the source of truth, locked after first
	money activity). Pre-currency teams fall back to INR, the historical base —
	their money caps stay unresolved until they pick a currency anyway.
	"""
	return frappe.db.get_value("Billing Profile", team, "currency") or "INR"


def threshold_for(level, currency):
	"""The level's money limits for a currency, or None if that rung doesn't
	exist in it."""
	return (level.get("thresholds") or {}).get(currency)


def cap_for(level, currency):
	"""The spend cap a level grants in a currency (0 when it doesn't price it)."""
	row = threshold_for(level, currency)
	return row.max_spend if row else 0


def get_ladder():
	"""Admin-defined ladder rungs, ordered low → high, each carrying its
	per-currency thresholds as `thresholds = {currency: {max_spend, min_cumulative_paid}}`."""
	levels = frappe.get_all(
		"Trust Tier Level", fields=list(_LEVEL_FIELDS), order_by="sequence asc"
	)
	by_parent: dict[str, dict] = {}
	for row in frappe.get_all(
		"Trust Tier Threshold",
		fields=["parent", "currency", "max_spend", "min_cumulative_paid"],
	):
		by_parent.setdefault(row.parent, {})[row.currency] = frappe._dict(
			max_spend=row.max_spend, min_cumulative_paid=row.min_cumulative_paid
		)
	for level in levels:
		level.thresholds = by_parent.get(level.name, {})
	return levels


def _entry_tier(levels):
	"""The rung every team lands on: the default level, else lowest sequence."""
	pool = [level for level in levels if level.is_default] or levels
	return min(pool, key=lambda level: level.sequence) if pool else None


def entry_level():
	"""The entry tier every new team lands on, or None if no ladder is seeded."""
	return _entry_tier(get_ladder())


def evaluate_tier(paid_invoice_count: int, cumulative_paid, currency, levels):
	"""Highest rung whose thresholds the team's paid history meets *in its currency*.

	A rung qualifies only when it prices `currency` AND both thresholds are met.
	With no qualifying rung, the entry tier applies.
	"""
	qualifying = []
	for level in levels:
		row = threshold_for(level, currency)
		if row is None:
			continue  # rung not offered in this currency
		if paid_invoice_count >= (level.min_paid_invoices or 0) and cumulative_paid >= (
			row.min_cumulative_paid or 0
		):
			qualifying.append(level)
	if not qualifying:
		return _entry_tier(levels)
	return max(qualifying, key=lambda level: level.sequence)


def get_team_caps(team: str):
	"""A team's effective entitlement caps, resolved LIVE from its Billing Profile.

	The tier is the level linked on the profile; the money cap is that level's
	threshold for the team's currency (or a bespoke `override_max_spend` when the
	team is manually pinned). Nothing is snapshotted — editing a level propagates
	to every team on it immediately.
	"""
	profile = (
		frappe.db.get_value(
			"Billing Profile",
			team,
			["currency", "trust_tier_level", "manual_override", "override_max_spend"],
			as_dict=True,
		)
		or frappe._dict()
	)
	currency = profile.currency or "INR"
	level = None
	if profile.trust_tier_level:
		level = next((l for l in get_ladder() if l.name == profile.trust_tier_level), None)
	# An untiered team has no resolved cap (0) — the same "no ceiling yet" signal
	# the old per-team-doc absence gave. A manual override still pins a bespoke cap.
	override = profile.override_max_spend if profile.manual_override else 0
	if level is None:
		return frappe._dict(
			tier=None, currency=currency, max_spend=override or 0, max_resource_count=0,
			allowed_plans=None, allowed_clusters=None, allowed_resource_types=None,
		)
	max_spend = override or cap_for(level, currency)
	return frappe._dict(
		tier=level.tier,
		currency=currency,
		max_spend=max_spend,
		max_resource_count=level.max_resource_count,
		allowed_plans=level.allowed_plans,
		allowed_clusters=level.allowed_clusters,
		allowed_resource_types=level.allowed_resource_types,
	)


def _tier_result(team: str, profile):
	"""Caps for `team` plus the profile's promotion-audit fields (the shape
	recompute/convert callers expect back)."""
	caps = get_team_caps(team)
	caps.promoted_at = profile.promoted_at
	caps.promotion_basis = profile.promotion_basis
	caps.manual_override = profile.manual_override
	return caps


def _profile_for(team: str):
	"""The team's Billing Profile (the per-team tier carrier), created blank if
	absent so a tier can always be recorded."""
	if frappe.db.exists("Billing Profile", team):
		return frappe.get_doc("Billing Profile", team)
	return frappe.get_doc({"doctype": "Billing Profile", "team": team})


def recompute_trust_tier(team: str, paid_invoice_count: int, cumulative_paid):
	"""Promote/demote a team from historical paid. Manual overrides are exempt.

	The tier lives on the team's single Billing Profile (no separate per-team
	doctype); the cap is resolved live from the level × the team's currency.
	Demotion lowers the cap only — it never stops running resources (that is a
	non-payment suspend directive, not a tier change).
	"""
	currency = team_currency(team)
	target = evaluate_tier(paid_invoice_count, cumulative_paid, currency, get_ladder())

	profile = _profile_for(team)
	if profile.manual_override:
		return _tier_result(team, profile)

	promoted = (profile.trust_tier or "") != target.tier
	profile.trust_tier_level = target.name
	profile.trust_tier = target.tier
	if promoted:
		profile.promoted_at = frappe.utils.now_datetime()
		profile.promotion_basis = (
			f"{paid_invoice_count} paid invoices + cumulative {cumulative_paid} → {target.tier}"
		)

	profile.save(ignore_permissions=True)

	# Mandate ceilings are tied to the cap; a raised cap needs customer re-consent
	# (the team is held at the old ceiling until re-authorisation). #08
	from central.billing.payments import mandates

	mandates.reconcile_mandates_to_cap(team)
	return _tier_result(team, profile)


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
	caps = get_team_caps(team)

	sliced_spend = sum((s.get("max_spend") or 0) for s in cluster_slices.values())
	if sliced_spend > (caps.max_spend or 0):
		frappe.throw(
			f"Cluster slices sum ({sliced_spend}) exceed team cap ({caps.max_spend})",
			frappe.ValidationError,
		)

	issued_at = frappe.utils.now_datetime()
	expires_at = frappe.utils.add_to_date(issued_at, hours=lifetime_hours)

	payload = {
		"team": team,
		"cluster_slices": cluster_slices,
		"allowed_plans": caps.allowed_plans or [],
		"allowed_resource_types": caps.allowed_resource_types or [],
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
