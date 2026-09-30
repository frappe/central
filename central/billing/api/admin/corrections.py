# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Admin corrections to an invoice: cancel it, or cancel it and refund the money."""

import frappe
from frappe import _

from central.billing import authz


@frappe.whitelist(methods=["POST"])
def cancel_invoice(invoice: str, reason: str) -> dict:
	"""Cancel an unpaid invoice. What it drew from the wallet goes back."""
	authz.require_operator()
	from central.billing.revenue.invoicing.lifecycle import cancel_invoice as cancel

	if not (reason or "").strip():
		frappe.throw(_("Give a reason for the cancellation."), frappe.ValidationError)
	cancel(invoice, reason=reason.strip())
	return {"invoice": invoice, "status": frappe.db.get_value("Invoice", invoice, "status")}
