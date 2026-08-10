# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Stop owing a pre-debit notice on the Stripe rail (ADR 0023, #111).

`requires_predebit_notice` means *we* send the notice and hold the debit 24 hours.
Stripe's India flow does that itself: confirming the off-session PaymentIntent is
what triggers the bank's notification, and Stripe then holds the intent in
`processing` for 26 hours. Running our window on top would make the customer wait
about two days and be told twice.

The earlier patch set the flag on every INR row, so this clears it where the
gateway does the work. The ₹15,000 ceiling stays on both rows — that one is the
RBI's, not the provider's.
"""

import frappe

# Gateways that issue the notification and hold the debit themselves.
SELF_NOTIFYING = ("Stripe",)


def execute():
	if not frappe.db.table_exists("Payment Gateway Currency"):
		return
	if not frappe.db.has_column("Payment Gateway Currency", "requires_predebit_notice"):
		return

	row = frappe.qb.DocType("Payment Gateway Currency")
	frappe.qb.update(row).set(row.requires_predebit_notice, 0).where(
		row.parent.isin(SELF_NOTIFYING)
	).run()
