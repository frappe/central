# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Namespace existing Credit Ledger Entry gateway_payment_ids by provider.

Top-up credits now store `{provider}:{payment_id}` so ids only unique within a
gateway can't collide across gateways. Existing rows hold the bare id. Without
this, a capture webhook still pending across the deploy would compose the new
`{provider}:{id}` key, miss the bare pre-deploy row, and double-credit.

Provider is read off the id's prefix — reliable for the gateways that actually
have a confirm-vs-webhook race (Razorpay `pay_`/`order_`, Stripe `pi_`/`ch_`).
PayPal capture ids have no such prefix, but PayPal top-ups are confirm-only (no
webhook race), so leaving those bare is safe. Idempotent: an already-namespaced
row (one containing ':') is skipped.
"""

import frappe


def _provider_for(payment_id: str) -> str | None:
	if payment_id.startswith(("pay_", "order_")):
		return "Razorpay"
	if payment_id.startswith(("pi_", "ch_")):
		return "Stripe"
	return None


def execute():
	rows = frappe.get_all(
		"Credit Ledger Entry",
		filters={"gateway_payment_id": ["is", "set"]},
		fields=["name", "gateway_payment_id"],
	)
	for row in rows:
		pid = row.gateway_payment_id
		if ":" in pid:  # already namespaced
			continue
		provider = _provider_for(pid)
		if not provider:
			continue
		frappe.db.set_value(
			"Credit Ledger Entry", row.name,
			"gateway_payment_id", f"{provider}:{pid}", update_modified=False,
		)
