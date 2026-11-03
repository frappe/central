# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Why a month's invoice count differs from the team count: one row per team, with its reason."""

import frappe
from frappe import _

from central.billing.doctype.billing_run_team import billing_run_team
from central.billing.doctype.invoice.invoice import is_issued
from central.billing.revenue.invoicing.run import billing_period

INVOICED = "Invoiced"
WAITING = "Waiting"
NEEDS_ACTION = "Needs Action"
WAIVED = "Waived (Internal)"
BELOW_MINIMUM = "Below Minimum"
NOTHING_TO_BILL = "Nothing to Bill"
NO_SUBSCRIPTION = "No Subscription"
STAGES = (INVOICED, WAITING, NEEDS_ACTION, WAIVED, BELOW_MINIMUM, NOTHING_TO_BILL, NO_SUBSCRIPTION)
_INDICATORS = {NEEDS_ACTION: "Red", WAITING: "Orange", INVOICED: "Green"}


def execute(filters: dict | None = None) -> tuple:
	filters = filters or {}
	# The month that just closed by default, the same month the Billing Day dashboard shows.
	period_end = filters.get("period_end") or billing_period()[1]
	rows = classify_teams(period_end)
	summary = _summary(rows)
	if filters.get("stage"):
		rows = [row for row in rows if row["stage"] == filters["stage"]]
	return _columns(), rows, _setup_message(), None, summary


def classify_teams(period_end) -> list[dict]:
	"""Every team that existed by month end, or that the run reached, with one result each.

	The first rule that matches wins. The results add up to the team count, which is
	what explains an invoice count far below the number of teams.
	"""
	facts = _Facts(frappe.utils.getdate(period_end))
	teams = frappe.get_all("Team", fields=["name", "team_name", "creation"])
	return [facts.row_for(team) for team in teams if facts.is_in_month(team)]


class _Facts:
	"""What one month's run needs to know about all teams, read once."""

	def __init__(self, period_end):
		self.period_end = period_end
		self.invoices = {
			row.team: row
			for row in frappe.get_all(
				"Invoice",
				filters={"period_end": period_end, "invoice_type": "Billable", "status": ["!=", "Cancelled"]},
				fields=["name", "team", "status", "total", "currency", "due_date", "hold_reason"],
			)
		}
		self.outcomes = {
			row.team: row
			for row in frappe.get_all(
				"Billing Run Team", filters={"period_end": period_end}, fields=["team", "outcome", "reason"]
			)
		}
		self.subscribed = set(frappe.get_all("Subscription", pluck="team", distinct=True))
		self.with_servers = set(frappe.get_all("Virtual Machine", pluck="team", distinct=True))
		self.internal = set(frappe.get_all("Billing Profile", filters={"is_internal": 1}, pluck="team"))

	def is_in_month(self, team) -> bool:
		joined_by_month_end = frappe.utils.getdate(team.creation) <= self.period_end
		return joined_by_month_end or team.name in self.invoices or team.name in self.outcomes

	def row_for(self, team) -> dict:
		invoice = self.invoices.get(team.name)
		stage, reason = self._invoice_result(invoice) if invoice else self._no_invoice_result(team)
		return {
			"team": team.name,
			"team_name": team.team_name,
			"is_internal": int(team.name in self.internal),
			"stage": stage,
			"reason": reason,
			"invoice": invoice.name if invoice else None,
			"amount": invoice.total if invoice else None,
			"currency": invoice.currency if invoice else None,
		}

	def _invoice_result(self, invoice) -> tuple[str, str]:
		if invoice.status == "Waived":
			return WAIVED, _("Internal team. The invoice is rated for the record and never collected.")
		if invoice.status == "Paid":
			return INVOICED, _("Paid.")
		if is_issued(invoice):
			return INVOICED, _("{0}, due {1}.").format(invoice.status, invoice.due_date)
		if invoice.hold_reason:
			return WAITING, _("Outstanding, not yet issued. Held for: {0}.").format(invoice.hold_reason)
		return WAITING, _("Outstanding. The next hourly sweep starts collection.")

	def _no_invoice_result(self, team) -> tuple[str, str]:
		outcome = self.outcomes.get(team.name)
		if not outcome:
			return self._no_run_result(team)
		if outcome.outcome == billing_run_team.FAILED:
			return NEEDS_ACTION, _("Invoice failed, retried every hour: {0}").format(outcome.reason)
		if outcome.outcome == billing_run_team.BELOW_MINIMUM:
			return BELOW_MINIMUM, outcome.reason
		return NOTHING_TO_BILL, outcome.reason or _("The invoice was cancelled.")

	def _no_run_result(self, team) -> tuple[str, str]:
		if team.name in self.subscribed:
			return WAITING, _("Has a subscription, and the run has not reached it yet.")
		if team.name in self.with_servers:
			return NO_SUBSCRIPTION, _(
				"Free trial servers only. A trial has no subscription, so it is not billed."
			)
		return NO_SUBSCRIPTION, _("Never created a server.")


def _summary(rows: list[dict]) -> list[dict]:
	counts = {stage: 0 for stage in STAGES}
	for row in rows:
		counts[row["stage"]] += 1
	cards = [
		_card(_("Teams by Month End"), len(rows), "Blue"),
		_card(_("Active Subscriptions"), frappe.db.count("Subscription", {"enabled": 1}), "Blue"),
	]
	cards += [_card(_(stage), counts[stage], _INDICATORS.get(stage, "Gray")) for stage in STAGES]
	return cards


def _card(label: str, value: int, indicator: str) -> dict:
	return {"label": label, "value": value, "datatype": "Int", "indicator": indicator}


def _setup_message() -> str | None:
	from central.billing.platform import readiness

	gaps = readiness.get_manual_setup_gaps()
	if not gaps:
		return None
	items = "".join(f"<li>{frappe.utils.escape_html(gap.detail)}</li>" for gap in gaps)
	return (
		f"<div class='alert alert-warning'><b>{_('Manual setup needed in Billing Settings')}</b>"
		f"<ul>{items}</ul><a href='/app/billing-settings'>{_('Open Billing Settings')}</a></div>"
	)


def _columns() -> list[dict]:
	return [
		{"fieldname": "team", "label": _("Team"), "fieldtype": "Link", "options": "Team", "width": 130},
		{"fieldname": "team_name", "label": _("Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "stage", "label": _("Result"), "fieldtype": "Data", "width": 160},
		{"fieldname": "reason", "label": _("Why"), "fieldtype": "Data", "width": 460},
		{"fieldname": "is_internal", "label": _("Internal"), "fieldtype": "Check", "width": 80},
		{
			"fieldname": "invoice",
			"label": _("Invoice"),
			"fieldtype": "Link",
			"options": "Invoice",
			"width": 170,
		},
		{
			"fieldname": "amount",
			"label": _("Amount"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"fieldname": "currency",
			"label": _("Currency"),
			"fieldtype": "Link",
			"options": "Currency",
			"width": 80,
		},
	]
