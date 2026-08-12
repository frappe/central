# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The team's own billing record, across periods rather than within one.

Everything on the Overview is scoped to the current cycle, and its trays explain
that cycle. What genuinely does not fit there is history: twelve months of spend,
where it went by product and region, every payment and refund across invoices, and
a statement an accountant can read. That is what this module serves.

The family/region grouping reuses the revenue reports' own helpers rather than
re-deriving them, so a customer's "cost per product" and the operator's services
revenue cannot disagree about what a line belongs to.

One thing deliberately absent: a downloadable tax invoice. ERPNext is the invoice
authority (ADR 0019) and the sync is strictly outbound, so the statutory document
is not ours to hand over yet. `get_tax_summary` reports what Central itself rated,
which is a working paper, not a filing.
"""

import csv
import io

import frappe
from frappe import _

from central.billing.api.dashboard._shared import _resolve_team, _team_currency

MAX_MONTHS = 36


@frappe.whitelist()
def get_spend_history(team: str | None = None, months: int = 12) -> dict:
	"""Month-by-month spend, and where it went by product family and region."""
	team = _resolve_team(team)
	months = max(1, min(int(months or 12), MAX_MONTHS))
	currency = _team_currency(team)
	start = frappe.utils.get_first_day(frappe.utils.add_months(frappe.utils.getdate(), -(months - 1)))

	invoices = frappe.get_all(
		"Invoice",
		filters={
			"team": team,
			"invoice_type": "Billable",
			"status": ["!=", "Cancelled"],
			"period_start": [">=", start],
		},
		fields=["name", "period_start", "total", "amount_paid", "status", "currency"],
		order_by="period_start asc",
	)

	lines = _line_items(team, start)
	return {
		"currency": currency,
		"from_date": str(start),
		"months": _by_month(invoices, months, currency),
		"by_product": _grouped(lines, "family"),
		"by_region": _grouped(lines, "region"),
		"total": frappe.utils.flt(sum(frappe.utils.flt(i.total) for i in invoices), 2),
		"invoice_count": len(invoices),
	}


@frappe.whitelist()
def get_statement(team: str | None = None, from_date: str | None = None, to_date: str | None = None) -> dict:
	"""Opening balance, what was charged, what was paid, what credits absorbed, and
	the balance left — the shape an accountant expects to be handed."""
	team = _resolve_team(team)
	currency = _team_currency(team)
	to_date = frappe.utils.getdate(to_date or frappe.utils.getdate())
	from_date = frappe.utils.getdate(from_date or frappe.utils.add_months(to_date, -12))

	invoices = frappe.get_all(
		"Invoice",
		filters={
			"team": team,
			"invoice_type": "Billable",
			"status": ["!=", "Cancelled"],
			"period_start": ["between", [from_date, to_date]],
		},
		fields=[
			"name",
			"period_start",
			"period_end",
			"status",
			"total",
			"credit_applied",
			"amount_paid",
			"output_tax_amount",
			"expected_collection",
		],
		order_by="period_start asc",
	)

	charged = sum(frappe.utils.flt(i.total) for i in invoices)
	paid = sum(frappe.utils.flt(i.amount_paid) for i in invoices)
	credited = sum(frappe.utils.flt(i.credit_applied) for i in invoices)
	return {
		"currency": currency,
		"from_date": str(from_date),
		"to_date": str(to_date),
		# The opening figure is what was still owed before this window began, so a
		# statement that starts mid-life does not read as though the team appeared
		# from nowhere with a clean slate.
		"opening_outstanding": _outstanding_before(team, from_date),
		"charged": frappe.utils.flt(charged, 2),
		"settled_by_credits": frappe.utils.flt(credited, 2),
		"settled_by_payment": frappe.utils.flt(paid, 2),
		"closing_outstanding": frappe.utils.flt(
			sum(
				frappe.utils.flt(i.expected_collection) - frappe.utils.flt(i.amount_paid)
				for i in invoices
				if i.status in ("Open", "Overdue")
			),
			2,
		),
		"rows": [
			{
				"invoice": i.name,
				"period_start": str(i.period_start),
				"period_end": str(i.period_end),
				"status": i.status,
				"total": frappe.utils.flt(i.total),
				"tax": frappe.utils.flt(i.output_tax_amount),
				"credit_applied": frappe.utils.flt(i.credit_applied),
				"amount_paid": frappe.utils.flt(i.amount_paid),
			}
			for i in invoices
		],
	}


@frappe.whitelist()
def get_tax_summary(team: str | None = None, from_date: str | None = None, to_date: str | None = None) -> dict:
	"""Tax charged and withheld per period, grouped by the mechanic that applied.

	A working paper, not a filing: the statutory invoice lives in ERPNext (ADR 0019),
	so this is what Central rated, said plainly, for someone reconciling against it.
	"""
	team = _resolve_team(team)
	currency = _team_currency(team)
	to_date = frappe.utils.getdate(to_date or frappe.utils.getdate())
	from_date = frappe.utils.getdate(from_date or frappe.utils.add_months(to_date, -12))

	invoices = frappe.get_all(
		"Invoice",
		filters={
			"team": team,
			"invoice_type": "Billable",
			"status": ["!=", "Cancelled"],
			"period_start": ["between", [from_date, to_date]],
		},
		fields=[
			"name",
			"period_start",
			"subtotal",
			"output_tax_type",
			"output_tax_rate",
			"output_tax_amount",
			"zero_rating_reason",
			"tds_amount",
			"total",
		],
		order_by="period_start asc",
	)

	by_type: dict[str, dict] = {}
	for inv in invoices:
		# `output_tax_type` is a Select whose "no tax applied" option is the literal
		# string "None" — truthy, and it would otherwise be shown to a customer as
		# the name of a tax.
		applied = (inv.output_tax_type or "").strip()
		if applied == "None":
			applied = ""
		key = applied or (_("Zero-rated") if inv.zero_rating_reason else _("No tax"))
		bucket = by_type.setdefault(key, {"tax_type": key, "taxable": 0.0, "tax": 0.0, "invoices": 0})
		bucket["taxable"] += frappe.utils.flt(inv.subtotal)
		bucket["tax"] += frappe.utils.flt(inv.output_tax_amount)
		bucket["invoices"] += 1

	return {
		"currency": currency,
		"from_date": str(from_date),
		"to_date": str(to_date),
		"by_type": [
			{**b, "taxable": frappe.utils.flt(b["taxable"], 2), "tax": frappe.utils.flt(b["tax"], 2)}
			for b in by_type.values()
		],
		"total_tax": frappe.utils.flt(sum(frappe.utils.flt(i.output_tax_amount) for i in invoices), 2),
		"total_withheld": frappe.utils.flt(sum(frappe.utils.flt(i.tds_amount) for i in invoices), 2),
		# Named so nobody mistakes this page for the filing document.
		"is_working_paper": True,
	}


@frappe.whitelist()
def list_refunds(team: str | None = None, limit: int = 50) -> list[dict]:
	"""Refunds raised on this team's payments.

	`gateway_reference` is the provider's own refund id — enough to quote back to
	support, but NOT the bank's ARN, which arrives later on a webhook we do not yet
	route. The UI must not imply a customer can trace this at their bank.
	"""
	team = _resolve_team(team)
	return [
		{
			"name": r.name,
			"invoice": r.invoice,
			"amount": frappe.utils.flt(r.amount),
			"currency": r.currency,
			"destination": r.destination,
			"status": r.status,
			"reason": r.reason,
			"gateway_reference": r.gateway_refund_id,
			"created_at": str(r.created_at or r.creation),
			"completed_at": str(r.completed_at) if r.completed_at else None,
		}
		for r in frappe.get_all(
			"Refund",
			filters={"team": team},
			fields=[
				"name",
				"invoice",
				"amount",
				"currency",
				"destination",
				"status",
				"reason",
				"gateway_refund_id",
				"created_at",
				"completed_at",
				"creation",
			],
			order_by="creation desc",
			limit=limit,
		)
	]


@frappe.whitelist()
def export_csv(report: str, team: str | None = None, from_date: str | None = None, to_date: str | None = None):
	"""Download one report as CSV. Sets the response directly — Frappe streams it."""
	team = _resolve_team(team)
	builders = {
		"statement": _statement_csv,
		"payments": _payments_csv,
		"spend": _spend_csv,
	}
	build = builders.get(report)
	if not build:
		frappe.throw(_("Unknown report: {0}").format(report), frappe.ValidationError)

	rows = build(team, from_date, to_date)
	buffer = io.StringIO()
	csv.writer(buffer).writerows(rows)
	frappe.response["type"] = "binary"
	frappe.response["filename"] = f"{report}-{frappe.utils.getdate()}.csv"
	frappe.response["filecontent"] = buffer.getvalue().encode("utf-8")
	frappe.response["doctype"] = None


def _statement_csv(team, from_date, to_date) -> list[list]:
	data = get_statement(team, from_date, to_date)
	rows = [["Invoice", "Period start", "Period end", "Status", "Total", "Tax", "Credits applied", "Paid"]]
	rows += [
		[
			r["invoice"],
			r["period_start"],
			r["period_end"],
			r["status"],
			r["total"],
			r["tax"],
			r["credit_applied"],
			r["amount_paid"],
		]
		for r in data["rows"]
	]
	return rows


def _payments_csv(team, from_date, to_date) -> list[list]:
	from central.billing.api.dashboard.invoices import list_payment_attempts

	rows = [["Date", "Invoice", "Amount", "Currency", "Status", "Gateway", "Reference", "Failure"]]
	rows += [
		[
			str(a["creation"]),
			a["invoice"],
			a["amount"],
			a["currency"],
			a["status"],
			a["gateway"],
			a["gateway_transaction_id"] or "",
			a["failure_reason"] or "",
		]
		for a in list_payment_attempts(team, limit=1000)
	]
	return rows


def _spend_csv(team, from_date, to_date) -> list[list]:
	data = get_spend_history(team, months=12)
	rows = [["Month", "Currency", "Billed", "Paid"]]
	rows += [[m["month"], data["currency"], m["total"], m["paid"]] for m in data["months"]]
	return rows


def _line_items(team: str, start) -> list[dict]:
	"""Line items enriched with the family and region a customer would name them by.

	Reuses the revenue reports' own resolution so the customer's "cost per product"
	and the operator's services-revenue report cannot disagree about a line.
	"""
	from central.billing.regions import region_label
	from central.billing.report._revenue import billable_line_items
	from central.billing.report.services_revenue.services_revenue import (
		VM_COMPUTE_FAMILY,
		_metered_resource_family_map,
		_plan_family_map,
	)

	lines = billable_line_items({"team": team, "from_date": str(start)})
	family_of_plan = _plan_family_map({line["plan"] for line in lines})
	family_of_rt = _metered_resource_family_map()

	out = []
	for line in lines:
		family = (
			family_of_plan.get(line["plan"])
			or family_of_rt.get(line["resource_type"])
			or (VM_COMPUTE_FAMILY if line["recurring"] else (line["resource_type"] or "").title())
			or _("Other")
		)
		out.append(
			{
				"family": family,
				"region": region_label(line["cluster"]) or _("Unassigned"),
				"amount": line["amount"],
			}
		)
	return out


def _grouped(lines: list[dict], key: str) -> list[dict]:
	"""Sum line amounts by one dimension, biggest first."""
	agg: dict[str, float] = {}
	for line in lines:
		agg[line[key]] = agg.get(line[key], 0.0) + frappe.utils.flt(line["amount"])
	return sorted(
		({"label": k, "amount": frappe.utils.flt(v, 2)} for k, v in agg.items()),
		key=lambda r: r["amount"],
		reverse=True,
	)


def _by_month(invoices, months: int, currency: str) -> list[dict]:
	"""One row per month in the window, including months with no invoice — a gap in
	a spend chart should read as a month with no spend, not as a missing bar."""
	totals: dict[str, dict] = {}
	for inv in invoices:
		key = frappe.utils.getdate(inv.period_start).strftime("%Y-%m")
		bucket = totals.setdefault(key, {"total": 0.0, "paid": 0.0})
		bucket["total"] += frappe.utils.flt(inv.total)
		bucket["paid"] += frappe.utils.flt(inv.amount_paid)

	out = []
	today = frappe.utils.getdate()
	for offset in range(months - 1, -1, -1):
		day = frappe.utils.add_months(today, -offset)
		key = day.strftime("%Y-%m")
		bucket = totals.get(key, {"total": 0.0, "paid": 0.0})
		out.append(
			{
				"month": key,
				"label": day.strftime("%b"),
				"total": frappe.utils.flt(bucket["total"], 2),
				"paid": frappe.utils.flt(bucket["paid"], 2),
				"currency": currency,
			}
		)
	return out


def _outstanding_before(team: str, before) -> float:
	"""What was still unpaid when the window opened."""
	rows = frappe.get_all(
		"Invoice",
		filters={
			"team": team,
			"invoice_type": "Billable",
			"status": ["in", ("Open", "Overdue")],
			"period_start": ["<", before],
		},
		fields=["expected_collection", "amount_paid"],
	)
	return frappe.utils.flt(
		sum(frappe.utils.flt(r.expected_collection) - frappe.utils.flt(r.amount_paid) for r in rows), 2
	)
