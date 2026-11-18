# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import datetime

import frappe
from frappe import _

from central.billing.ingester import connection

DOCTYPE = "Monthly Exchange Rate"


def month_rate(from_currency: str, to_currency: str, on, store: bool = True) -> frappe._dict:
	"""The rate a month converts `from_currency` at, as {rate, rate_date}: read once, then kept."""
	# One rate per month (ADR 0027): the Overview, the price list and the invoice all use it.
	if from_currency == to_currency:
		return frappe._dict(rate=1.0, rate_date=None)
	month = frappe.utils.getdate(on).replace(day=1)
	key = {"month": month, "from_currency": from_currency, "to_currency": to_currency}
	stored = frappe.db.get_value(DOCTYPE, key, ["rate", "rate_date"], as_dict=True)
	if stored:
		return stored
	found = accounting_rate(from_currency, to_currency, month)
	if not found:
		frappe.throw(
			_("The accounting system has no {0} to {1} exchange rate on or before {2}.").format(
				from_currency, to_currency, month
			)
		)
	# A page view reads the rate without writing it; billing stores it.
	if store:
		_store(key, found)
	return frappe._dict(rate=frappe.utils.flt(found.exchange_rate), rate_date=found.date)


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


def check_converted_usage_has_a_rate() -> list:
	"""Every currency AI is billed in has a USD rate in the accounting system for the next draft."""
	from central.billing.platform.invariants import Violation
	from central.billing.revenue.usage_ledger import utc_today
	from central.services.doctype.service.service import AI_SERVICE
	from central.services.doctype.team_service.team_service import billed_subjects

	if not connection.enabled():
		return []
	teams = list({service.team for service in billed_subjects(AI_SERVICE).values()})
	currencies = frappe.get_all(
		"Billing Profile",
		filters={"name": ["in", teams or [""]], "currency": ["!=", "USD"]},
		pluck="currency",
		distinct=True,
	)
	return [
		Violation(
			check="M2",
			subject_doctype="Currency",
			subject=currency,
			detail=f"The accounting system has no USD to {currency} rate, so AI cannot be billed in {currency}.",
		)
		for currency in currencies
		if not accounting_rate("USD", currency, utc_today())
	]


def _store(key: dict, found: frappe._dict) -> None:
	try:
		frappe.db.savepoint("monthly_exchange_rate")
		# Written by billing on the first read of the month; Desk only reads it.
		frappe.get_doc(
			{
				"doctype": DOCTYPE,
				**key,
				"rate": frappe.utils.flt(found.exchange_rate),
				"rate_date": found.date,
				"source": found.name,
			}
		).insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		# Another worker stored the same month first, from the same record.
		frappe.db.rollback(save_point="monthly_exchange_rate")
