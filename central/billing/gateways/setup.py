# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Seed the fixed roster of Payment Gateway rows — one per supported adapter.

An adapter is a code-level capability, not user data: the set of providers we can
talk to is whatever `gateways.registry.get_adapter` knows how to build. So the
admin never *creates* a gateway, they fill in keys on a row that already exists
and flip Enabled. Seeded rows start disabled and blank, which is inert — nothing
resolves to a gateway that isn't enabled.

Runs on install, on migrate, and before tests (same reasons as the catalog masters
seed): patches are skipped on fresh installs, so the roster can't live only there.
"""

import frappe


def ensure_gateway_records():
	"""Create a disabled, blank row for every adapter that has no row yet.

	Idempotent, and never touches an existing row — a configured gateway's keys,
	currencies and enabled state survive every migrate.
	"""
	for adapter_key in adapter_keys():
		if frappe.db.exists("Payment Gateway", adapter_key):
			continue
		doc = frappe.get_doc({"doctype": "Payment Gateway", "adapter_key": adapter_key, "is_enabled": 0})
		# No keys to prove yet — validation would have nothing to call.
		doc.flags.skip_credential_validation = True
		doc.insert(ignore_permissions=True)


def adapter_keys() -> list[str]:
	"""The adapters this build supports, read off the Select field so the roster and
	the dropdown can never drift apart."""
	meta = frappe.get_meta("Payment Gateway")
	options = meta.get_field("adapter_key").options or ""
	return [key.strip() for key in options.split("\n") if key.strip()]
