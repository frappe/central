# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Admin Gateway Config API — issue #49.

Provides the data layer for the Gateway Config panel: the list of configured
gateways with their currency rows, and a read-only effective routing table
(one row per currency → which gateway currently wins). No secrets are returned.
"""

import frappe

from central.billing import authz


@frappe.whitelist()
def get_gateways() -> list[dict]:
	"""All configured gateways with their currencies child rows.

	Secrets (api_key, api_secret, webhook_secret) are never included.
	"""
	authz.require(authz.MANAGE)
	gateways = frappe.get_all(
		"Payment Gateway",
		fields=["name", "title", "adapter_key", "is_enabled", "supports_mandates",
				"credentials_validated_at", "webhook_endpoint_id"],
		order_by="creation asc",
	)
	for gw in gateways:
		gw["currencies"] = frappe.get_all(
			"Payment Gateway Currency",
			filters={"parent": gw.name},
			fields=["name", "currency", "is_default"],
			order_by="idx asc",
		)
	return gateways


@frappe.whitelist()
def get_effective_routing() -> list[dict]:
	"""Read-only summary: for each configured currency, which gateway wins.

	A currency appears in this table only when at least one enabled gateway has
	an is_default row for it. Currencies that are configured but have no default
	are listed with gateway = None so the admin can see the gap.
	"""
	authz.require(authz.MANAGE)

	# Collect every currency that appears in any gateway's child table.
	all_rows = frappe.get_all(
		"Payment Gateway Currency",
		fields=["currency", "is_default", "parent"],
		order_by="currency asc",
	)

	currencies = sorted({r.currency for r in all_rows if r.currency})
	routing = []
	for currency in currencies:
		default_rows = [
			r for r in all_rows
			if r.currency == currency and r.is_default
			and frappe.db.get_value("Payment Gateway", r.parent, "is_enabled")
		]
		gateway = default_rows[0].parent if default_rows else None
		adapter_key = frappe.db.get_value("Payment Gateway", gateway, "adapter_key") if gateway else None
		routing.append({
			"currency": currency,
			"gateway": gateway,
			"adapter_key": adapter_key,
		})
	return routing


@frappe.whitelist()
def set_default_gateway(gateway: str, currency: str) -> dict:
	"""Make `gateway` the default handler for `currency`.

	Finds (or creates) the currency row on the gateway and sets is_default = True.
	The PaymentGateway controller's _enforce_default_uniqueness clears the flag on
	any previously-default gateway for the same currency.
	"""
	authz.require(authz.MANAGE)

	gw_doc = frappe.get_doc("Payment Gateway", gateway)
	row = next((r for r in gw_doc.currencies if r.currency == currency), None)
	if row:
		row.is_default = 1
	else:
		gw_doc.append("currencies", {"currency": currency, "is_default": 1})
	gw_doc.save(ignore_permissions=True)
	return {"gateway": gateway, "currency": currency, "is_default": 1}
