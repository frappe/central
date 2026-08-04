# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Admin dashboard endpoints (issue #19).

Cost-Explorer-style aggregates + drill-down, plus the operational panels. Every
endpoint requires Central's operator bypass (System Manager) — a customer (or
the Agent API key) gets a 403. None of these are team-scoped: an operator sees
across all teams. (A dedicated `billing:operate` capability is deferred — ADR
0004 §3.)

Split into domain modules (revenue / teams / catalog) over shared helpers; this
package re-exports the public API so every `billing.api.admin.*` path holds.
"""

from central.billing.api.admin.catalog import (
	create_configured_plan,
	get_catalog,
	get_cluster_consumption,
	get_conversion,
	get_plan_consumption,
	get_trial_costs_detail,
	get_trial_detail,
	update_plan_rate,
)
from central.billing.api.admin.revenue import (
	get_cluster_breakdown,
	get_free_trial_costs,
	get_overdue_aging,
	get_payment_analytics,
	get_revenue_trend,
	get_summary,
	get_team_breakdown,
	list_all_invoices,
)
from central.billing.api.admin.teams import (
	adjust_team_credits,
	get_delinquent_teams,
	get_metrics,
	get_payment_failures,
	get_retention,
	get_team_billing,
	list_teams,
)

__all__ = [
	"get_summary",
	"get_revenue_trend",
	"get_cluster_breakdown",
	"get_team_breakdown",
	"get_payment_analytics",
	"get_overdue_aging",
	"get_free_trial_costs",
	"list_all_invoices",
	"get_team_billing",
	"get_retention",
	"get_metrics",
	"list_teams",
	"get_payment_failures",
	"get_delinquent_teams",
	"adjust_team_credits",
	"get_catalog",
	"update_plan_rate",
	"create_configured_plan",
	"get_cluster_consumption",
	"get_plan_consumption",
	"get_conversion",
	"get_trial_detail",
	"get_trial_costs_detail",
]
