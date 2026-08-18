# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Admin console: a team's team-level metered services (ADR 0013/0015).

Operators see what metered services a team has subscribed to and can subscribe it
to a new one or switch it onto a different plan in the same family (an upgrade). All
endpoints are operator-gated and take an explicit `team` — an admin acts across teams,
unlike the pilot facade which is fixed to its own team.
"""

import frappe

from central.billing.api.dashboard._shared import _team_currency, require_billing_profile
from central.billing.authz import require_operator


@frappe.whitelist()
def get_team_services(team: str, cluster: str | None = None) -> dict:
	"""A team's metered footprint plus the catalog it can subscribe to: the active
	service subscriptions (subject, plan, modes, allowance, current usage) and the
	available service plans priced for the team's currency."""
	require_operator()
	from central.billing.catalog.services import list_service_plans, team_service_subscriptions

	currency = _team_currency(team)
	return {
		"team": team,
		"currency": currency,
		"services": team_service_subscriptions(team),
		"available_plans": list_service_plans(currency, cluster=cluster),
	}


@frappe.whitelist(methods=["POST"])
def subscribe_team_service(team: str, plan: str, cluster: str | None = None) -> dict:
	"""Subscribe a team to a team-level service, or switch it onto a different plan in
	the same family (an upgrade). Idempotent per (team, family, cluster). Requires the
	team's billing profile to be complete."""
	require_operator()
	require_billing_profile(team, "subscribe to a service")
	from central.billing.catalog.subscriptions import provision_service_subscription

	return provision_service_subscription(team, plan, cluster=cluster)
