# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Billing Invariant Violations — the money facts that no longer add up.

Every row is a place where two independent derivations of the same number disagree:
a wallet whose balance is not its ledger, an invoice whose subtotal is not its lines,
a payment we believe we captured with no attempt behind it.

**An empty report is the success case.** This is the one report you want blank.

It recomputes live from `platform.invariants` — the same function the daily audit
runs, so what the job asserts and what a human reads can never drift apart. Nothing is
stored, so there is no snapshot to go stale.

Amounts are split per currency: INR and USD never share a column or a total
(report/_currency.split_currency_columns).
"""

import frappe
from frappe import _

from central.billing.platform import invariants
from central.billing.report._currency import split_currency_columns


def execute(filters: dict | None = None):
	filters = filters or {}
	violations = invariants.audit(only=filters.get("check") or None)

	if filters.get("team"):
		violations = [v for v in violations if v.team == filters["team"]]

	rows = [
		{
			"check": v.check,
			"title": invariants.CHECKS[v.check][0],
			"team": v.team,
			"subject_doctype": v.subject_doctype,
			"subject": v.subject,
			"currency": v.currency,
			"expected": v.expected,
			"actual": v.actual,
			"drift": v.drift,
			"detail": v.detail,
		}
		for v in violations
	]

	# Splits expected/actual/drift into one column per currency when the run spans more
	# than one, and drops the standalone currency column. Mutates `rows` in place.
	columns = split_currency_columns(_columns(), rows, ("expected", "actual", "drift"))
	return columns, rows, _message(rows), _chart(violations)


def _message(rows: list[dict]) -> str:
	if not rows:
		return _("✅ Every money invariant holds. This report is meant to be empty.")
	return _(
		"⚠️ {0} violation(s). Each is a number the system derives two ways and gets two "
		"answers for — money has drifted. Worst drift first."
	).format(len(rows))


def _chart(violations: list) -> dict | None:
	if not violations:
		return None
	counts: dict[str, int] = {}
	for v in violations:
		counts[v.check] = counts.get(v.check, 0) + 1
	labels = sorted(counts)
	return {
		"data": {
			"labels": [f"{k} — {invariants.CHECKS[k][0]}" for k in labels],
			"datasets": [{"name": _("Violations"), "values": [counts[k] for k in labels]}],
		},
		"type": "bar",
	}


def _columns() -> list[dict]:
	return [
		{"label": _("Check"), "fieldname": "check", "fieldtype": "Data", "width": 70},
		{"label": _("Invariant"), "fieldname": "title", "fieldtype": "Data", "width": 240},
		{"label": _("Team"), "fieldname": "team", "fieldtype": "Link", "options": "Team",
		 "width": 150},
		{"label": _("Subject"), "fieldname": "subject", "fieldtype": "Dynamic Link",
		 "options": "subject_doctype", "width": 170},
		{"label": _("Type"), "fieldname": "subject_doctype", "fieldtype": "Data", "width": 130},
		# expected / actual / drift are expanded per currency by split_currency_columns,
		# which drops this column when it does — INR and USD never share a total.
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link",
		 "options": "Currency", "width": 90},
		{"label": _("Expected"), "fieldname": "expected", "fieldtype": "Currency", "width": 120},
		{"label": _("Actual"), "fieldname": "actual", "fieldtype": "Currency", "width": 120},
		{"label": _("Drift"), "fieldname": "drift", "fieldtype": "Currency", "width": 120},
		{"label": _("What broke"), "fieldname": "detail", "fieldtype": "Data", "width": 420},
	]
