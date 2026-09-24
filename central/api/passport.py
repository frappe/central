# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt
"""The pilot-facing Frappe sign-in facade.

A site pulls its own Passport registration through its bench's pilot. The team comes
from the verified pilot credential, never from a request parameter, and the site must
belong to that team and be bound to that same credential — so one bench can never
fetch another site's client secret.

Central vouches that the site owns its address, and nothing more. Who may sign in is
the site's own user list.
"""

from __future__ import annotations

from contextlib import contextmanager

import frappe
from frappe import _

from central.api.pilot import pilot_credential_auth
from central.integrations.passport import registration_for


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def registration(site: str) -> dict:
	"""Everything a site needs to offer Frappe sign-in."""
	row = _owned_site(site)

	with _as_operator():
		return registration_for(row)


def _owned_site(site: str) -> dict:
	credential = frappe.local.pilot_credential
	row = frappe.db.get_value(
		"Site",
		site,
		["name", "team", "url", "status", "subdomain", "pilot_credential_id"],
		as_dict=True,
	)

	if not row or row.team != credential.team or row.pilot_credential_id != credential.name:
		frappe.throw(_("Not permitted for this site."), frappe.PermissionError)

	return row


@contextmanager
def _as_operator():
	"""Run the registration write as Administrator: the pilot is a guest session, and the
	team and site are already fixed by the verified credential."""
	user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		yield
	finally:
		frappe.set_user(user)
