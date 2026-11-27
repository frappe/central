# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Usage Month rows by their key: insert the missing ones, find a line's row, and read corrections."""

import datetime
from typing import TYPE_CHECKING

import frappe

if TYPE_CHECKING:
	from central.billing.revenue.usage_month import MonthRow

DOCTYPE = "Usage Month"
CORRECTION = "Usage Month Correction"
META_FIELDS = ("name", "creation", "modified", "owner", "modified_by")
KEY_FIELDS = ("service", "subject", "meter", "dimension", "month", "subscription")
CONTEXT_FIELDS = ("aggregation", "team", "resource_type", "unit")


def month_of(on) -> datetime.date:
	"""The first day of the month of `on`."""
	return frappe.utils.getdate(on).replace(day=1)


def row_key(row) -> tuple:
	"""The month key of a line or a month row, without its subscription."""
	return (
		row["service"],
		row["subject"],
		row["meter"],
		row.get("dimension") or "",
		month_of(row.get("day") or row.get("month")),
	)


def month_for(months: dict, row: dict) -> "MonthRow | None":
	"""The row that holds the line's day, else the row of the line's subscription."""
	candidates = months.get(row_key(row), [])
	day = frappe.utils.getdate(row["day"]).day
	for month in candidates:
		if month.has_day(day):
			return month
	# A row inserted by a worker that committed after this transaction began is not seen.
	return next((month for month in candidates if month.record["subscription"] == row["subscription"]), None)


def insert_missing(rows: list[dict], now) -> None:
	"""Insert an empty month row for each line's month and subscription that has none."""
	user = frappe.session.user
	keys = {(*row_key(row), row["subscription"]): row for row in rows}
	values = [
		(
			frappe.generate_hash(length=12),
			now,
			now,
			user,
			user,
			*key,
			*(row.get(name) for name in CONTEXT_FIELDS),
		)
		for key, row in keys.items()
	]
	frappe.db.bulk_insert(
		DOCTYPE,
		[*META_FIELDS, *KEY_FIELDS, *CONTEXT_FIELDS],
		values,
		ignore_duplicates=True,
	)


def rated_rows(meter, month) -> list[frappe._dict]:
	"""A meter's month rows of `month`, locked in name order, with how they were rated."""
	meter_month = {key: meter[key] for key in ("subscription", "resource_type", "dimension")}
	return frappe.qb.get_query(
		DOCTYPE,
		filters={**meter_month, "month": month},
		fields=["name", "counted_at", "invoice", "rate_date", "terms_corrected"],
		order_by="name asc",
		for_update=True,
	).run(as_dict=True)


def corrections_of(names: list[str]) -> dict[str, list]:
	"""The corrections of these month rows by row, in the order they were made."""
	if not names:
		return {}
	rows = frappe.get_all(
		CORRECTION,
		filters={"parent": ["in", names], "parenttype": DOCTYPE},
		fields=["name", "parent", "idx", "day", "value", "as_of", "status", "report", "invoice"],
		order_by="idx asc, creation asc",
	)
	by_parent: dict[str, list] = {}
	for row in rows:
		by_parent.setdefault(row.parent, []).append(row)
	return by_parent
