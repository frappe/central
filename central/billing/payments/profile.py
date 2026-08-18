# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""
Billing Profile read/write helpers for a team.

The gateway-customer logic (mint-or-reuse a customer id per team+gateway, stored
in a Gateway Customer row and committed before the order so a partial setup never
orphans it) lives in central.billing.payments.payments.ensure_gateway_customer —
the single place both the top-up and payment-method flows provision through.
"""

import frappe


def create_or_update_billing_profile(team: str, **values):
	"""Creates or updates the billing profile for the team and returns the doc."""
	if frappe.db.exists("Billing Profile", team):
		doc = frappe.get_doc("Billing Profile", team)
		doc.update(values)
	else:
		doc = frappe.get_doc({"doctype": "Billing Profile", "team": team, **values})
	doc.save(ignore_permissions=True)
	return doc


def get_billing_profile(team: str):
	"""Returns the billing profile for the team."""
	return frappe.get_doc("Billing Profile", team)
