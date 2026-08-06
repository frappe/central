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
	mode: str = "Derived",
	assume: str | None = None,
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
	return engine.project(team, period_start, period_end, today=today, mode=mode, assume=assume)


@frappe.whitelist()
def project_team_months(
	team: str,
	start: str | None = None,
	months: int = 6,
	today: str | None = None,
	mode: str = "Derived",
	assume: str | None = None,
) -> dict:
	"""Roll a team forward over several months, carrying what each one changes.

	The question a single period cannot answer: not what September costs, but when the
	credits run out and what happens after.
	"""
	authz.require_operator()

	today = frappe.utils.getdate(today or frappe.utils.nowdate())
	start = frappe.utils.getdate(start or frappe.utils.get_first_day(today))
	months = max(1, min(frappe.utils.cint(months), 24))

	frappe.logger("billing").info(
		f"projection: {frappe.session.user} rolled {team} forward {months} months "
		f"from {start} as of {today}"
	)
	return engine.project_months(team, start, months=months, today=today, mode=mode, assume=assume)
