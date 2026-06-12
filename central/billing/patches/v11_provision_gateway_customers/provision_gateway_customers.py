# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Provision a Gateway Customer for every team that already has a billing profile.

ensure_gateway_customer mints lazily on the first payment-method setup; this
front-loads it for existing teams. For each billing profile with a currency, it
resolves the default gateway for that currency and ensures a (team, gateway)
customer — reusing one already stored (so it's idempotent and re-runnable).

Each team is isolated: a gateway error — auth/network, or a pre-existing orphaned
customer we no longer recover automatically (fail_existing was dropped) — is
logged and skipped, never aborting the migrate.

NOTE: this makes a live gateway API call per not-yet-provisioned team. It is safe
to re-run; teams that already have a Gateway Customer row are skipped without a
call.
"""

import frappe


def execute():
	from central.billing.gateways.registry import (
		GatewayNotFound,
		get_adapter,
		resolve_gateway_for_currency,
	)
	from central.billing.payments.payments import ensure_gateway_customer

	for profile in frappe.get_all(
		"Billing Profile", filters={"currency": ["is", "set"]}, fields=["name", "currency"]
	):
		team = profile.name  # Billing Profile is autonamed field:team, so name == team
		try:
			gateway = resolve_gateway_for_currency(profile.currency)
		except GatewayNotFound:
			continue  # no gateway for this currency — nothing to provision against
		if frappe.db.exists("Gateway Customer", {"team": team, "gateway": gateway}):
			continue

		try:
			adapter = get_adapter(frappe.get_doc("Payment Gateway", gateway))
			ensure_gateway_customer(team, gateway, adapter)  # mints + commits the row
		except Exception:
			# One team's gateway failure (orphan / auth / network) must not abort the
			# migrate — discard its partial state and move on.
			frappe.db.rollback()
			frappe.log_error(
				title="v11 provision gateway customer",
				message=f"team={team} gateway={gateway}\n{frappe.get_traceback()}",
			)
