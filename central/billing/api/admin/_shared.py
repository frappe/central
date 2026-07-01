# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Shared helpers + constants for the admin dashboard endpoints.

Period filters, INR normalisation (teams bill in mixed currencies), and the
active-price-lock / plan-rate lookups the aggregates are built from.
"""

import frappe

AGING_BUCKETS = [("0-7", 0, 7), ("8-15", 8, 15), ("16-30", 16, 30), ("30+", 31, 10**9)]
_BILLABLE_LIVE = ("Open", "Paid", "Overdue")
# Teams bill in mixed currencies; normalise revenue to INR for one comparable axis.
_FX_TO_INR = {"INR": 1.0, "EUR": 90.0, "USD": 83.0}
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_STANDING_RANK = {"Current": 0, "Past Due": 1, "Suspended": 2}


def _period_filter(field, from_date, to_date):
	f = []
	if from_date:
		f.append([field, ">=", from_date])
	if to_date:
		f.append([field, "<=", to_date])
	return f


def _to_inr(amount, currency) -> float:
	"""Normalise a native-currency amount to an INR-equivalent for cross-team
	aggregates (teams bill in INR/EUR/USD; summing raw would be meaningless)."""
	return frappe.utils.flt(amount) * _FX_TO_INR.get(currency, 1.0)


def _team_currency(team: str) -> str:
	# Billing Profile currency is the source of truth; fall back to an open-segment
	# currency (legacy teams) then INR.
	from central.billing.catalog.subscriptions import team_active_segments

	seg_currency = next((s.currency for s in team_active_segments(team) if s.currency), None)
	return frappe.db.get_value("Billing Profile", team, "currency") or seg_currency or "INR"


def _plan_monthly_inr(plan: str, cluster: str | None) -> float:
	from central.billing.catalog.pricing import get_catalog_rates, resolve_rate

	if not plan or not frappe.db.exists("Plan", plan):
		return 0.0
	return frappe.utils.flt(resolve_rate(get_catalog_rates("Plan", plan), "INR", cluster))


def _asset_cluster_map(asset_ids) -> dict:
	"""Map asset_id -> cluster in one query. Cluster lives on the Asset now (the
	runtime record), not the Subscription (cdea38e); admin aggregates resolve a
	subscription's region through its asset_id."""
	ids = [a for a in set(asset_ids) if a]
	if not ids:
		return {}
	return {
		r.name: r.cluster
		for r in frappe.get_all("Asset", filters={"name": ["in", ids]}, fields=["name", "cluster"])
	}


def _active_segments(filters=None):
	"""Every team's open billing segment (team, cluster, plan, locked_rate), resolved
	from the `Subscription Change` ledger — the retired `Price Lock`'s replacement for
	admin consumption aggregates (#86). Composed configs are now included, so a region
	running only custom servers is no longer invisible in cluster/plan consumption."""
	from central.billing.catalog.subscriptions import active_segments

	return active_segments(filters)
