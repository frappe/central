# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Mark existing top-ups as paid-in credit, the way new ones are booked."""

import frappe


def execute():
	cle = frappe.qb.DocType("Credit Ledger Entry")
	frappe.qb.update(cle).set(cle.paid_in, 1).where(
		cle.gateway_payment_id.isnotnull() & (cle.gateway_payment_id != "")
	).run()
