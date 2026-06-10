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
	return frappe.db.get_value("Price Lock", {"team": team}, "currency") or "INR"


def _plan_monthly_inr(plan: str, cluster: str | None) -> float:
	from central.billing.catalog.pricing import get_catalog_rates, resolve_rate

	if not plan or not frappe.db.exists("Plan", plan):
		return 0.0
	return frappe.utils.flt(resolve_rate(get_catalog_rates("Plan", plan), "INR", cluster))


def _active_locks(filters=None):
	f = {"ended_at": ["is", "not set"]}
	if filters:
		f.update(filters)
	return frappe.get_all("Price Lock", filters=f, fields=["team", "cluster", "plan", "locked_rate"])
