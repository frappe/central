# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A team's customer id at one payment gateway.

Created once per (team, gateway) the moment the gateway customer is minted, and
committed immediately — so a setup that fails *after* the customer exists at the
gateway never orphans it. Every later payment-method setup and recurring charge
reuses this id, and a team can hold one row per gateway (e.g. Razorpay + Stripe
for an INR team that falls back across gateways, or Stripe abroad).

The PK is `{team}::{gateway}` (Expression autoname), so uniqueness per team+
gateway is enforced by the primary key — a second insert raises DuplicateEntry.
"""

from frappe.model.document import Document


class GatewayCustomer(Document):
	pass
