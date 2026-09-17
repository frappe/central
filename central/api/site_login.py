# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt
"""Site login through the server runtime that owns its sessions."""

from __future__ import annotations

import frappe

from central.integrations.pilot import fetch_site_login_url


def site_login_url(doc) -> str | None:
	"""Exchange a Central assertion with the site's own Pilot."""
	return _pilot_site_login_url(doc)


def _pilot_site_login_url(doc) -> str | None:
	"""Use the active credential and running server gateway for the site's own Team."""
	if not doc.pilot_credential_id:
		return None
	credential = frappe.qb.DocType("Pilot Credential")
	asset = frappe.qb.DocType("Asset")
	row = (
		frappe.qb.from_(credential)
		.inner_join(asset)
		.on(credential.asset == asset.name)
		.select(credential.audience_id, asset.gateway_url, asset.status)
		.where(
			(credential.name == doc.pilot_credential_id)
			& (credential.status == "Active")
			& (credential.team == doc.team)
			& (asset.team == doc.team)
		)
	).run(as_dict=True)
	if not row or row[0].status != "Running":
		return None
	gateway = (row[0].gateway_url or "").rstrip("/")
	if not gateway:
		return None
	return fetch_site_login_url(gateway, row[0].audience_id, doc.name)
