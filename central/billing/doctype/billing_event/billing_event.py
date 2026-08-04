# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Billing Event — the append-only, derived transition/money stream (ADR 0016).

Written only by `billing.states.transition()`. It is a projection: no pricing,
invoicing, settlement, dunning or entitlement code may read it, so dropping the table
would not change a single invoice total. Its readers are engineers debugging, the
admin UI, and the reports.
"""

from frappe.model.document import Document


class BillingEvent(Document):
	pass
