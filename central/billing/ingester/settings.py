# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Reading the accounting settings on Billing Settings, and the choices made from them."""

import frappe
from frappe import _

from central.billing.india_gst import INDIA
from central.billing.ingester.connection import enabled


def accounting_settings():
	"""Billing Settings, for its Accounting tab. Refused while the accounting sync is off."""
	if not enabled():
		frappe.throw(_("The accounting sync is off, so the accounting settings are not in use."))
	return frappe.get_cached_doc("Billing Settings")


def invoice_series(team: str) -> str:
	"""The naming series for this team's next statutory invoice.

	Outside India is one series, because those supplies carry no GST. Inside India
	a live GSTIN makes it B2B, anything else B2C.
	"""
	from central.billing.revenue import gst_status

	settings = accounting_settings()
	country = frappe.db.get_value("Billing Profile", team, "country")
	if country != INDIA:
		return settings.series_overseas
	if gst_status.standing(team).gstin:
		return settings.series_india_b2b
	return settings.series_india_b2c


def receivable_account(currency: str) -> str:
	"""The receivable account an invoice in `currency` is booked to."""
	return _account_for(currency, "account", _("receivable account"))


def advance_account(currency: str) -> str:
	"""The account a top-up in `currency` is held in until an invoice uses it."""
	return _account_for(currency, "advance_account", _("advance account"))


def income_account(currency: str) -> str:
	"""The account invoice lines in `currency` are booked to."""
	return _account_for(currency, "income_account", _("income account"))


def wallet_clearing_account(currency: str) -> str:
	"""The account wallet credit passes through when it is given back, in `currency`."""
	return _account_for(currency, "wallet_clearing_account", _("wallet clearing account"))


def _account_for(currency: str, field: str, label: str) -> str:
	for row in accounting_settings().receivable_accounts:
		if row.currency == currency and row.get(field):
			return row.get(field)
	frappe.throw(_("Billing Settings has no {0} for {1}.").format(label, currency))
