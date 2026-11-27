# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import datetime

import frappe

from central.billing.platform.invariants import Violation
from central.billing.revenue.usage_corrections import WINDOW_DAYS, get_day_of
from central.billing.revenue.usage_month import CORRECTION, CREDIT_DUE, DOCTYPE, WRITTEN_OFF
from central.billing.revenue.usage_month_rows import corrections_of


def check_credit_due_corrections() -> list[Violation]:
	"""Every lower value for a billed day has had its credit note issued by an operator.

	Issue the credit note for the difference, then mark the correction Credited."""
	correction = frappe.qb.DocType(CORRECTION)
	month = frappe.qb.DocType(DOCTYPE)
	rows = (
		frappe.qb.from_(correction)
		.join(month)
		.on(correction.parent == month.name)
		.select(
			correction.name,
			correction.idx,
			correction.day,
			correction.billed_value,
			correction.value,
			month.name.as_("month_row"),
			month.team,
			month.subject,
			month.month,
		)
		.where(correction.status == CREDIT_DUE)
		.orderby(correction.name)
		.limit(200)
	).run(as_dict=True)
	later = _later_values(rows)
	return [
		Violation(
			check="M4",
			team=row.team,
			subject_doctype=DOCTYPE,
			subject=row.month_row,
			detail=_credit_due_detail(row, later.get(row.name, [])),
		)
		for row in rows
	]


def check_reissued_corrections() -> list[Violation]:
	"""Every value a reissue gave back under a later charge or credit note has been settled by an operator."""
	correction = frappe.qb.DocType(CORRECTION)
	month = frappe.qb.DocType(DOCTYPE)
	rows = (
		frappe.qb.from_(correction)
		.join(month)
		.on(correction.parent == month.name)
		.select(
			correction.name,
			correction.day,
			correction.value,
			correction.billable_delta,
			correction.invoice,
			month.name.as_("month_row"),
			month.team,
			month.subject,
			month.month,
		)
		# Only release writes off a correction that names an invoice; past its window nothing is charged.
		.where(
			(correction.status == WRITTEN_OFF)
			& correction.invoice.isnotnull()
			& (
				correction.billed_invoice_date
				>= frappe.utils.getdate() - datetime.timedelta(days=WINDOW_DAYS)
			)
		)
		.orderby(correction.name)
		.limit(200)
	).run(as_dict=True)
	return [
		Violation(
			check="M7",
			team=row.team,
			subject_doctype=DOCTYPE,
			subject=row.month_row,
			detail=_reissued_detail(row),
		)
		for row in rows
	]


def _reissued_detail(row) -> str:
	"""The readiness detail for one correction a reissue left to an operator."""
	billed = f"{row.subject} on {get_day_of(row):%d %b %Y}: {row.value} was billed on {row.invoice}"
	later = "a later charge or credit note of this day was rated against it"
	return (
		f"{billed}, which was reissued, and {later}. Bill the {row.billable_delta} it added by hand, "
		f"then mark correction {row.name} Billed By Hand."
	)


def _later_values(rows: list) -> dict[str, list]:
	"""For each Credit Due correction, the corrections of its day made after it."""
	corrections = corrections_of(list({row.month_row for row in rows}))
	return {
		row.name: [
			c
			for c in corrections.get(row.month_row, [])
			if c.day == row.day and frappe.utils.cint(c.idx) > frappe.utils.cint(row.idx)
		]
		for row in rows
	}


def _credit_due_detail(row, later: list) -> str:
	"""The readiness detail for one Credit Due correction."""
	detail = f"{row.subject} on {get_day_of(row):%d %b %Y}: billed {row.billed_value}, now {row.value}."
	if later:
		# A later value may undo the drop, so the operator sees it before issuing a credit note.
		values = ", ".join(f"{c.value} ({c.status})" for c in later)
		detail += f" Later values of this day: {values}; check them before crediting."
	return detail + f" Issue the credit note, then mark correction {row.name} Credited."
