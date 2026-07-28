# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Failed payments — a glance view of which invoices aren't collecting, and why.

One row per **invoice** with failed charges (not per attempt): an invoice with
three declined retries is ONE uncollected invoice, not three, so the row carries
an Attempts count and the latest failure detail (Stripe `decline_code` /
Razorpay `error_reason` beside the top-level code). Counting attempts as rows
would triple-count the amount not collected. Attempts with no invoice (e.g.
top-ups) stay on their own row. Pair it with Gateway Payment Success Ratio,
which gives the aggregate rate; this one names the individual failures.
"""

import frappe
from frappe import _
from frappe.utils import flt

from central.billing.report._currency import split_currency_columns


def execute(filters: dict | None = None):
	filters = filters or {}
	attempts = _failed_attempts(filters)
	rows = _by_invoice(attempts)
	columns = _columns()
	chart = _reason_chart(rows)
	summary = _summary(rows, attempts)
	columns = split_currency_columns(columns, rows, ["amount"])
	return columns, rows, None, chart, summary


def _by_invoice(attempts: list[dict]) -> list[dict]:
	"""Collapse failed attempts to one row per invoice, newest failure first. Attempts
	arrive newest-first, so the first one seen for an invoice supplies the representative
	amount + latest failure detail; every attempt bumps the invoice's `attempts` count.
	Attempts carrying no invoice can't be deduped, so each stays its own row."""
	by_invoice: dict[str, dict] = {}
	rows: list[dict] = []
	for a in attempts:
		invoice = a.get("invoice")
		if not invoice:
			rows.append({**a, "attempts": 1})
			continue
		row = by_invoice.get(invoice)
		if row is None:
			row = {**a, "attempts": 0}
			by_invoice[invoice] = row
			rows.append(row)
		row["attempts"] += 1
	return rows


def _failed_attempts(filters: dict) -> list[dict]:
	conditions = {"status": "Failed"}
	for field in ("gateway", "team", "decline_code"):
		if filters.get(field):
			conditions[field] = filters[field]
	if filters.get("from_date") and filters.get("to_date"):
		conditions["initiated_at"] = ["between", [filters["from_date"], filters["to_date"]]]
	elif filters.get("from_date"):
		conditions["initiated_at"] = [">=", filters["from_date"]]
	elif filters.get("to_date"):
		conditions["initiated_at"] = ["<=", filters["to_date"]]
	return frappe.get_all(
		"Payment Attempt",
		filters=conditions,
		fields=[
			"name",
			"initiated_at",
			"team",
			"invoice",
			"gateway",
			"payment_method",
			"amount",
			"currency",
			"retry_number",
			"failure_code",
			"decline_code",
			"failure_reason",
		],
		order_by="initiated_at desc",
	)


def _columns() -> list[dict]:
	return [
		{
			"label": _("Invoice"),
			"fieldname": "invoice",
			"fieldtype": "Link",
			"options": "Invoice",
			"width": 150,
		},
		{"label": _("Team"), "fieldname": "team", "fieldtype": "Link", "options": "Team", "width": 140},
		{"label": _("Last Failed At"), "fieldname": "initiated_at", "fieldtype": "Datetime", "width": 165},
		{"label": _("Attempts"), "fieldname": "attempts", "fieldtype": "Int", "width": 90},
		{"label": _("Amount"), "fieldname": "amount", "fieldtype": "Float", "width": 100},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 80},
		{
			"label": _("Gateway"),
			"fieldname": "gateway",
			"fieldtype": "Link",
			"options": "Payment Gateway",
			"width": 120,
		},
		{"label": _("Failure Code"), "fieldname": "failure_code", "fieldtype": "Data", "width": 150},
		{"label": _("Decline Code"), "fieldname": "decline_code", "fieldtype": "Data", "width": 160},
		{"label": _("Reason"), "fieldname": "failure_reason", "fieldtype": "Data", "width": 280},
		{
			"label": _("Latest Attempt"),
			"fieldname": "name",
			"fieldtype": "Link",
			"options": "Payment Attempt",
			"width": 150,
		},
	]


def _reason(row: dict) -> str:
	"""The most specific label available for a failure: the granular decline code,
	then the top-level code, then a catch-all."""
	return row.get("decline_code") or row.get("failure_code") or _("(unknown)")


def _reason_chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	counts: dict[str, int] = {}
	for r in rows:
		counts[_reason(r)] = counts.get(_reason(r), 0) + 1
	top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
	return {
		"data": {
			"labels": [k for k, _c in top],
			"datasets": [{"name": _("Failures"), "values": [c for _k, c in top]}],
		},
		"type": "bar",
	}


def _summary(rows: list[dict], attempts: list[dict]) -> list[dict]:
	if not attempts:
		return [{"label": _("Failed Attempts"), "value": 0, "datatype": "Int", "indicator": "green"}]
	teams = len({a.get("team") for a in attempts if a.get("team")})
	# Amount not collected is per DISTINCT invoice (one row = one invoice), grouped by
	# currency — INR and USD don't sum together.
	amount_by_currency: dict[str, float] = {}
	for r in rows:
		amount_by_currency[r.get("currency") or "?"] = amount_by_currency.get(
			r.get("currency") or "?", 0.0
		) + flt(r.get("amount"))
	# Top reason counts distinct invoices (their latest failure), consistent with the rows.
	counts: dict[str, int] = {}
	for r in rows:
		counts[_reason(r)] = counts.get(_reason(r), 0) + 1
	top_reason, top_count = max(counts.items(), key=lambda kv: kv[1])

	summary = [
		{"label": _("Invoices Affected"), "value": len(rows), "datatype": "Int", "indicator": "red"},
		{"label": _("Failed Attempts"), "value": len(attempts), "datatype": "Int", "indicator": "orange"},
	]
	for currency in sorted(amount_by_currency):
		summary.append(
			{
				"label": _("Not Collected ({0})").format(currency),
				"value": flt(amount_by_currency[currency], 2),
				"datatype": "Float",
				"indicator": "red",
			}
		)
	summary.append({"label": _("Teams Affected"), "value": teams, "datatype": "Int", "indicator": "orange"})
	summary.append({"label": _("Top Reason"), "value": f"{top_reason} ({top_count})", "datatype": "Data"})
	return summary
