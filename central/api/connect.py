from __future__ import annotations

import frappe
from frappe import _

from central.iam import get_user_team_names, is_active_team_member, user_has_operator_bypass
from central.utils.guards import require_capability

# Single home for every API method that crosses the central<->connect boundary —
# both endpoints connect calls on central, and (later) helpers central uses to fetch
# data from connect. Kept in one file for now since the traffic is low and one-sided;
# split by direction/concern once it's more generic. No site-to-site auth exists yet
# between the two sites (tracked separately) — this is intentionally open
# (allow_guest) until that lands.


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


# --- Partner Client Link workflow (Phase 2) -----------------------------------
# These four are the sync surface connect's approve/reject/delink UI will call once
# it exists. `acting_user` is accepted explicitly because there's no shared session
# between the sites yet (same phase-0 gap as above) — connect will pass the partner
# user's identity at face value until real site-to-site auth lands. When called from
# within central itself (an authenticated request, no connect involved), omit
# `acting_user` and the caller's own session is used instead.


@frappe.whitelist(methods=["POST"])
@require_capability("billing:manage", _("You can't set up a partner link for this team."))
def request_partner_link(team: str, partner_code: str) -> dict:
	"""Customer-initiated: resolve `partner_code` to a Partner Profile and create a
	Pending Partner Client Link. `connect_membership` is left blank — there's no
	connect Partner Membership to reference yet (see the TODO on that field)."""
	partner_code = partner_code.strip()
	partner_team = frappe.db.get_value("Partner Profile", {"partner_code": partner_code}, "team")
	if not partner_team:
		frappe.throw(_("Invalid partner code."))

	link = frappe.get_doc(
		{
			"doctype": "Partner Client Link",
			"partner_team": partner_team,
			"client_team": team,
			"status": "Pending",
		}
	)
	# The capability check above is the real gate; the Partner Client Link's own
	# DocType permissions don't grant portal users create rights directly.
	link.insert(ignore_permissions=True)
	return {"name": link.name, "partner_team": partner_team, "status": link.status}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def approve_partner_link(name: str, acting_user: str | None = None) -> dict:
	doc = frappe.get_doc("Partner Client Link", name)
	doc.approve(acting_user)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def reject_partner_link(name: str, acting_user: str | None = None) -> dict:
	doc = frappe.get_doc("Partner Client Link", name)
	doc.reject(acting_user)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def delink_partner_link(name: str, acting_user: str | None = None) -> dict:
	doc = frappe.get_doc("Partner Client Link", name)
	doc.delink(acting_user)
	return {"name": doc.name, "status": doc.status}


# --- Fetching from connect (central.integrations.connect.ConnectClient) ------


@frappe.whitelist(methods=["GET"])
def fetch_connect_partner(connect_partner: str) -> dict:
	"""A connect Partner's marketplace listing, for display on that partner's own
	central dashboard — gated to a member of the Team whose Partner Profile
	references it (or an operator)."""
	from central.integrations.connect import ConnectClient

	team = frappe.db.get_value("Partner Profile", {"connect_partner": connect_partner}, "team")
	if not team:
		frappe.throw(_("No Partner Profile references {0}.").format(connect_partner))
	if not user_has_operator_bypass() and not is_active_team_member(frappe.session.user, team):
		frappe.throw(_("Not permitted for this partner."), frappe.PermissionError)

	return ConnectClient().get_partner(connect_partner)
