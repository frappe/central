# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The operator-facing entry point onto projections.

Lives in the API layer because that is where whitelisted endpoints belong — the
projection package stays domain-only and exposes no HTTP surface.

Cross-team by nature — an operator asks about somebody else's money — so this is
gated on the operator capability rather than on team scoping, and every call is
logged with who asked and about whom.
"""

import frappe

from central.billing import authz
from central.billing.projection import engine


@frappe.whitelist()
def project_team(
	team: str,
	period_start: str | None = None,
	period_end: str | None = None,
	today: str | None = None,
) -> dict:
	"""Project one team over one period.

	Defaults to the month in flight, which is the question an operator usually has:
	what is this team about to be billed, and what happens after that.
	"""
	authz.require_operator()

	today = frappe.utils.getdate(today or frappe.utils.nowdate())
	period_start = frappe.utils.getdate(period_start or frappe.utils.get_first_day(today))
	period_end = frappe.utils.getdate(period_end or frappe.utils.get_last_day(period_start))

	frappe.logger("billing").info(
		f"projection: {frappe.session.user} projected {team} "
		f"for {period_start}..{period_end} as of {today}"
	)
	return engine.project(team, period_start, period_end, today=today)
