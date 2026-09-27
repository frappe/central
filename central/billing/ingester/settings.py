# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Reading Accounting Settings, and the choices made from them."""

import frappe
from frappe import _

from central.billing.india_gst import INDIA
from central.billing.ingester.connection import enabled


def accounting_settings():
	"""Accounting Settings. Refused while the accounting sync is off."""
	if not enabled():
		frappe.throw(_("The accounting sync is off, so Accounting Settings are not in use."))
	return frappe.get_cached_doc("Accounting Settings")


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
