# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Reads the day values that usage month rows keep."""

import frappe

from central.billing.revenue.usage_month import (
	DAY_FIELDS,
	READ_FIELDS,
	bit,
	days_of,
	slots_of,
)
from central.billing.revenue.usage_month_rows import CONTEXT_FIELDS, DOCTYPE, KEY_FIELDS, month_of


def day_rows(filters: dict, day=None) -> list[frappe._dict]:
	"""The filled days of the month rows that match `filters`, one dict per day, oldest first."""
	# A row past retention keeps no day values.
	filters = {"pruned": 0, **filters}
	if day:
		filters = {**filters, "month": month_of(day)}
	months = frappe.get_all(DOCTYPE, filters=filters, fields=list(READ_FIELDS), order_by="month asc")
	days = [_day_row(month, number) for month in months for number in _filled_days(month)]
	if day:
		days = [row for row in days if row.day == frappe.utils.getdate(day)]
	return sorted(days, key=lambda row: (row.day, row.dimension, row.subject))


def subjects_with_day(service: str, day) -> set[str]:
	"""The subjects of a service that have a value for a UTC day."""
	table = frappe.qb.DocType(DOCTYPE)
	day = frappe.utils.getdate(day)
	return set(
		(
			frappe.qb.from_(table)
			.select(table.subject)
			.distinct()
			.where(
				(table.service == service)
				& (table.month == month_of(day))
				& (table.filled.bitwiseand(bit(day.day)) != 0)
			)
		).run(pluck=True)
	)


def invoice_of_day(row, day: int) -> str | None:
	"""The invoice that billed a day of a month row, or None."""
	return slots_of(row.get("slots")).get(str(day), {}).get("invoice")


def billed_days_of(rows: list, invoice: str) -> list[tuple]:
	"""Each (month row, day, slot) of `rows` that the invoice billed."""
	return [
		(row, int(day), slot)
		for row in rows
		for day, slot in slots_of(row.get("slots")).items()
		if slot.get("invoice") == invoice
	]


def _day_row(month, day: int) -> frappe._dict:
	slot = slots_of(month.slots).get(str(day), {})
	return frappe._dict(
		{key: month[key] for key in (*KEY_FIELDS, *CONTEXT_FIELDS)},
		month_row=month.name,
		day=month.month.replace(day=day),
		quantity=frappe.utils.flt(month[DAY_FIELDS[day - 1]]),
		included=frappe.utils.flt(slot.get("included")),
		estimated=int(bool(month.estimated & bit(day))),
		written_off=int(bool(month.written_off & bit(day))),
		invoice=slot.get("invoice"),
		as_of=frappe.utils.get_datetime(slot["as_of"]) if slot.get("as_of") else None,
		landed_at=frappe.utils.get_datetime(slot["landed_at"]) if slot.get("landed_at") else None,
		source=slot.get("source"),
		report=slot.get("report"),
		source_amount=frappe.utils.flt(slot.get("amount")),
		source_currency=slot.get("currency"),
	)


def _filled_days(month) -> list[int]:
	return days_of(frappe.utils.cint(month.filled))
