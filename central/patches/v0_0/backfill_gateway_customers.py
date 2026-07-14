# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Backfill Gateway Customer rows from existing Payment Methods.

The gateway customer id used to live only on the Payment Method, created after a
successful setup — so a setup that failed after minting the customer orphaned it.
It now lives in a per-(team, gateway) Gateway Customer row, written and committed
the moment the customer is minted. Seed that store from the customer ids already
recorded on Payment Methods so existing teams reuse their customer rather than
minting a new one. Idempotent: skips a (team, gateway) already present.
"""

import frappe


def execute():
	rows = frappe.get_all(
		"Payment Method",
		filters={"gateway_customer_id": ["is", "set"]},
		fields=["team", "gateway", "gateway_customer_id"],
	)
	seen = set()
	for r in rows:
		key = (r.team, r.gateway)
		if not (r.team and r.gateway and r.gateway_customer_id) or key in seen:
			continue
		seen.add(key)
		if frappe.db.exists("Gateway Customer", {"team": r.team, "gateway": r.gateway}):
			continue
		frappe.get_doc({
			"doctype": "Gateway Customer",
			"team": r.team,
			"gateway": r.gateway,
			"adapter_key": frappe.db.get_value("Payment Gateway", r.gateway, "adapter_key"),
			"gateway_customer_id": r.gateway_customer_id,
		}).insert(ignore_permissions=True)
