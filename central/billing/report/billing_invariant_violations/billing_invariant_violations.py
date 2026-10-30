# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from central.billing.platform import invariants, readiness
from central.billing.report._currency import split_currency_columns
from central.billing.report._paging import first_rows

KINDS = {"Money": invariants.CHECKS, "Readiness": readiness.CHECKS}


def _selected_checks(filters: dict) -> dict:
	"""The checks the filters ask for, as {code: (kind, title)}."""
	only = filters.get("check") or None
	return {
		code: (kind, title)
		for kind, registry in KINDS.items()
		if not filters.get("kind") or kind == filters["kind"]
		for code, (title, _fn) in registry.items()
		if not only or code == only
	}


def _title(check: str) -> str:
	return next(registry[check][0] for registry in KINDS.values() if check in registry)


def _violations(filters: dict, selected: dict) -> list:
	found = []
	for registry in KINDS.values():
		for code in registry:
			if code in selected:
				found.extend(invariants.audit(only=code, checks=registry))
	if filters.get("team"):
		found = [v for v in found if v.team == filters["team"]]
	return sorted(found, key=lambda v: abs(v.drift), reverse=True)


def execute(filters: dict | None = None):
	filters = filters or {}
	selected = _selected_checks(filters)
	violations = _violations(filters, selected)
	if filters.get("view") == "Summary":
		return _summary(violations, selected)

	rows = [
		{
			"check": v.check,
			"title": _title(v.check),
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
	rows, message = first_rows(rows, _message(rows))
	return columns, rows, message, _chart(violations)


def _summary(violations: list, selected: dict):
	"""One row per check that ran: how many violations, across how many teams."""
	rows = []
	for check, (kind, title) in selected.items():
		hits = [v for v in violations if v.check == check]
		rows.append(
			{
				"check": check,
				"kind": kind,
				"title": title,
				"violations": len(hits),
				"teams": len({v.team for v in hits if v.team}),
				"example": hits[0].detail if hits else "",
			}
		)
	rows.sort(key=lambda row: (-row["violations"], row["check"]))
	columns = [
		{"label": _("Check"), "fieldname": "check", "fieldtype": "Data", "width": 70},
		{"label": _("Kind"), "fieldname": "kind", "fieldtype": "Data", "width": 100},
		{"label": _("What it asserts"), "fieldname": "title", "fieldtype": "Data", "width": 280},
		{"label": _("Violations"), "fieldname": "violations", "fieldtype": "Int", "width": 100},
		{"label": _("Teams"), "fieldname": "teams", "fieldtype": "Int", "width": 80},
		{"label": _("Example"), "fieldname": "example", "fieldtype": "Data", "width": 460},
	]
	return columns, rows, _message(violations), _chart(violations)


def _message(rows: list) -> str:
	if not rows:
		return _("✅ Every money invariant and readiness check holds. This report is meant to be empty.")
	return _(
		"⚠️ {0} violation(s). Money checks are numbers the system derives two ways and gets two "
		"answers for; readiness checks are data the next billing run would bill wrongly. Worst drift first."
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
			"labels": [f"{k} — {_title(k)}" for k in labels],
			"datasets": [{"name": _("Violations"), "values": [counts[k] for k in labels]}],
		},
		"type": "bar",
	}


def _columns() -> list[dict]:
	return [
		{"label": _("Check"), "fieldname": "check", "fieldtype": "Data", "width": 70},
		{"label": _("Invariant"), "fieldname": "title", "fieldtype": "Data", "width": 240},
		{"label": _("Team"), "fieldname": "team", "fieldtype": "Link", "options": "Team", "width": 150},
		{
			"label": _("Subject"),
			"fieldname": "subject",
			"fieldtype": "Dynamic Link",
			"options": "subject_doctype",
			"width": 170,
		},
		{"label": _("Type"), "fieldname": "subject_doctype", "fieldtype": "Data", "width": 130},
		# expected / actual / drift are expanded per currency by split_currency_columns,
		# which drops this column when it does — INR and USD never share a total.
		{
			"label": _("Currency"),
			"fieldname": "currency",
			"fieldtype": "Link",
			"options": "Currency",
			"width": 90,
		},
		{"label": _("Expected"), "fieldname": "expected", "fieldtype": "Currency", "width": 120},
		{"label": _("Actual"), "fieldname": "actual", "fieldtype": "Currency", "width": 120},
		{"label": _("Drift"), "fieldname": "drift", "fieldtype": "Currency", "width": 120},
		{"label": _("What broke"), "fieldname": "detail", "fieldtype": "Data", "width": 420},
	]
