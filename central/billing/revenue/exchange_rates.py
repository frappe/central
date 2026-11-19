# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import datetime

import frappe
from frappe import _

from central.billing.ingester import connection

DOCTYPE = "Monthly Exchange Rate"


def month_rate(from_currency: str, to_currency: str, on) -> frappe._dict:
	"""The rate a month converts `from_currency` at, as {rate, rate_date, fixed}. Reads only."""
	# The Overview, the recount and the invoice all use this one rate for the month.
	if from_currency == to_currency:
		return frappe._dict(rate=1.0, rate_date=None, fixed=True)
	key = month_key(from_currency, to_currency, on)
	return stored_rate(key) or _as_rate(_required_rate(key), fixed=False)


def fix_month_rate(from_currency: str, to_currency: str, on, final: bool = False) -> frappe._dict:
	"""The month's rate, stored once it is the 1st's, or with `final` whatever the latest is."""
	found = month_rate(from_currency, to_currency, on)
	key = month_key(from_currency, to_currency, on)
	# Until then a later reading may still find the 1st's rate, so the rate is not kept.
	if found.fixed or not (final or found.rate_date == key["month"]):
		return found
	return _store(key, found)


def stored_rate(key: dict) -> frappe._dict | None:
	"""The rate kept for a month, if one was."""
	stored = frappe.db.get_value(DOCTYPE, key, ["rate", "rate_date"], as_dict=True)
	return frappe._dict(stored, fixed=True) if stored else None


def accounting_rate(from_currency: str, to_currency: str, month: datetime.date) -> frappe._dict | None:
	"""The latest selling rate the accounting system holds on or before the 1st."""
	rows = connection.find(
		"Currency Exchange",
		[
			["from_currency", "=", from_currency],
			["to_currency", "=", to_currency],
			["for_selling", "=", 1],
			["date", "<=", str(month)],
		],
		fields=["name", "date", "exchange_rate"],
		order_by="date desc",
		limit=1,
	)
	return rows[0] if rows else None


def month_key(from_currency: str, to_currency: str, on) -> dict:
	"""The filters of a month's stored rate."""
	month = frappe.utils.getdate(on).replace(day=1)
	return {"month": month, "from_currency": from_currency, "to_currency": to_currency}


def _required_rate(key: dict) -> frappe._dict:
	found = accounting_rate(key["from_currency"], key["to_currency"], key["month"])
	if not found:
		frappe.throw(
			_("The accounting system has no {0} to {1} exchange rate on or before {2}.").format(
				key["from_currency"], key["to_currency"], key["month"]
			)
		)
	return found


def _as_rate(found: frappe._dict, fixed: bool) -> frappe._dict:
	return frappe._dict(
		rate=frappe.utils.flt(found.exchange_rate),
		rate_date=frappe.utils.getdate(found.date),
		source=found.name,
		fixed=fixed,
	)


def _store(key: dict, found: frappe._dict) -> frappe._dict:
	try:
		frappe.db.savepoint("monthly_exchange_rate")
		# Written by billing on the first read of the month; Desk only reads it.
		frappe.get_doc(
			{
				"doctype": DOCTYPE,
				**key,
				"rate": found.rate,
				"rate_date": found.rate_date,
				"source": found.source,
			}
		).insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		# Another worker stored the month first. Its rate is the month's, even if this read differs.
		frappe.db.rollback(save_point="monthly_exchange_rate")
		stored = frappe.db.get_value(DOCTYPE, key, ["rate", "rate_date"], as_dict=True, for_update=True)
		# The other worker's row can be gone again if it rolled back; then this reading stays unstored.
		return frappe._dict(stored, fixed=True) if stored else found
	return frappe._dict(found, fixed=True)
