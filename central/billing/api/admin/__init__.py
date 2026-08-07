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
from central.billing.api.admin.projection import (
	project_team,
	project_team_months,
	sample_cohort,
	size_cohort,
	start_cohort_projection,
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
	"project_team",
	"project_team_months",
	"sample_cohort",
	"size_cohort",
	"start_cohort_projection",
	"adjust_team_credits",
	"create_configured_plan",
	"get_catalog",
	"get_cluster_breakdown",
	"get_cluster_consumption",
	"get_conversion",
	"get_delinquent_teams",
	"get_free_trial_costs",
	"get_metrics",
	"get_overdue_aging",
	"get_payment_analytics",
	"get_payment_failures",
	"get_plan_consumption",
	"get_retention",
	"get_revenue_trend",
	"get_summary",
	"get_team_billing",
	"get_team_breakdown",
	"get_trial_costs_detail",
	"get_trial_detail",
	"list_all_invoices",
	"list_teams",
	"update_plan_rate",
]
