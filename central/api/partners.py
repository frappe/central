from __future__ import annotations

import frappe
from frappe import _

from central.iam import get_user_team_names

# Called by connect when a Partner is registered/activated there. No site-to-site
# auth exists yet between central and connect (tracked separately) — this is
# intentionally open (allow_guest) until that lands.


@frappe.whitelist(allow_guest=True, methods=["POST"])
def register_partner_profile(connect_partner: str, contact_email: str, contact_full_name: str | None = None) -> dict:
	"""Idempotent: returns the existing Partner Profile if one already exists for
	`connect_partner`, otherwise provisions a central User + Team for the contact
	(or reuses their existing team) and creates the Partner Profile."""
	connect_partner = connect_partner.strip()
	contact_email = contact_email.strip().lower()
	if not connect_partner or not contact_email:
		frappe.throw(_("connect_partner and contact_email are required."))

	existing = frappe.db.get_value(
		"Partner Profile",
		{"connect_partner": connect_partner},
		["name", "team", "partner_code"],
		as_dict=True,
	)
	if existing:
		return existing

	team = _get_or_create_team_for_contact(contact_email, contact_full_name)

	profile = frappe.get_doc(
		{
			"doctype": "Partner Profile",
			"team": team,
			"connect_partner": connect_partner,
		}
	)
	profile.insert(ignore_permissions=True)
	return {"name": profile.name, "team": profile.team, "partner_code": profile.partner_code}


def _get_or_create_team_for_contact(contact_email: str, contact_full_name: str | None) -> str:
	teams = get_user_team_names(contact_email)
	if teams:
		return teams[0]

	if not frappe.db.exists("User", contact_email):
		full_name = (contact_full_name or contact_email).strip()
		first_name, _sep, last_name = full_name.partition(" ")
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": contact_email,
				"first_name": first_name or contact_email,
				"last_name": last_name or None,
				"enabled": 1,
				"user_type": "Website User",
				"send_welcome_email": 1,
			}
		)
		user.flags.ignore_permissions = True
		user.insert(ignore_permissions=True)

	# `User.after_insert` (central.users.bootstrap_user_team) provisions a personal
	# Team for the new user synchronously, so it's available immediately here.
	teams = get_user_team_names(contact_email)
	if not teams:
		frappe.throw(_("Could not provision a Team for {0}.").format(contact_email))
	return teams[0]
