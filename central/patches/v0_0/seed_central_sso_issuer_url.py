# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Carry the `central_url` site-config value onto Central SSO Settings.

The token issuer / JWKS base URL used to be read from the `central_url` conf key;
it is the `issuer_url` field on Central SSO Settings now. This copies a deployment's
configured value over so the `iss` claim and JWKS URL are unchanged the day of the
deploy. A one-time patch, not a migrate hook, so clearing it later isn't undone.
"""

import frappe


def execute():
	value = frappe.conf.get("central_url")
	if not value:
		return
	frappe.db.set_single_value("Central SSO Settings", "issuer_url", value)
