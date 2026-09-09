# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt
"""The pilot-facing Frappe sign-in facade.

A site pulls its own Passport registration through its bench's pilot. The team comes
from the verified pilot credential, never from a request parameter, and the site must
belong to that team and be bound to that same credential — so one bench can never
fetch another site's client secret.
"""

from __future__ import annotations

from contextlib import contextmanager

import frappe
from frappe import _

from central.api.pilot import pilot_credential_auth
from central.integrations.passport import registration_for

SITE_ROLE_HINT = "System Manager"


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def registration(site: str) -> dict:
	"""Everything a site needs to offer Frappe sign-in, plus who may use it."""
	row = _owned_site(site)

	with _as_operator():
		return {**registration_for(row), "members": _members(row)}


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


def _members(site: dict) -> list[dict]:
	"""The team members entitled to this site, with the local role they should get.

	Frappe Cloud already hands every entitled member a one-click Administrator session,
	so a per-person System Manager is the same privilege with an audit trail. Anything
	narrower is a product decision this facade deliberately does not make.
	"""
	member = frappe.qb.DocType("Team Member")
	rows = (
		frappe.qb.from_(member)
		.select(member.user)
		.distinct()
		.where(
			(member.parenttype == "Team")
			& (member.parentfield == "members")
			& (member.parent == site["team"])
			& (member.status == "Active")
			& (
				(member.resource_type == "*")
				| ((member.resource_type == "Site") & (member.resource_name == site["name"]))
			)
		)
	).run(as_dict=True)

	return [{"email": row.user, "role": SITE_ROLE_HINT} for row in rows]


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
