# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Customer dashboard: a team's own team-level metered services (ADR 0013/0015).

Team-scoped via the capability IAM like every dashboard endpoint: the read needs
`billing:view`, the subscribe mutation `billing:manage`. The team defaults to the
caller's own and is never silently widened.
"""

import frappe

from central.billing import authz
from central.billing.api.dashboard._shared import _resolve_team, _team_currency


@frappe.whitelist()
def get_metered_services(team: str | None = None, cluster: str | None = None) -> dict:
	"""The team's metered service footprint (subject, plan, modes, allowance, current
	usage) plus the service catalog it can subscribe to, priced for its currency."""
	from central.billing.catalog.services import list_service_plans, team_service_subscriptions

	team = _resolve_team(team)
	currency = _team_currency(team)
	return {
		"currency": currency,
		"services": team_service_subscriptions(team),
		"available_plans": list_service_plans(currency, cluster=cluster),
	}


@frappe.whitelist(methods=["POST"])
def subscribe_metered_service(plan: str, cluster: str | None = None, team: str | None = None) -> dict:
	"""Subscribe the team to a team-level service, or switch it onto a different plan in
	the same family (an upgrade). Idempotent per (team, family, cluster)."""
	from central.billing.api.dashboard._shared import require_billing_profile
	from central.billing.catalog.subscriptions import provision_service_subscription

	team = _resolve_team(team, require=authz.MANAGE)
	require_billing_profile(team, "subscribe to a service")
	return provision_service_subscription(team, plan, cluster=cluster)
