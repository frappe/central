# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Notification dashboard API — customer-facing endpoints for preferences and events."""

import frappe

from central.api.pilot import pilot_credential_auth


@frappe.whitelist(methods=["POST"])
def save_user_preferences(team: str, preferences: list[dict]) -> dict:
	"""Create or update the calling user's notification preferences for *team*.

	``preferences`` is a list of dicts, each with:
	  - ``category``: Billing | Server | Team
	  - ``email_enabled``: 0 | 1
	  - ``in_app_enabled``: 0 | 1

	Upserts per (user, team, category). Returns the saved preferences."""
	user = frappe.session.user
	saved = []
	for pref in preferences:
		category = pref.get("category")
		if not category:
			continue
		email = bool(frappe.utils.cint(pref.get("email_enabled", 1)))
		in_app = bool(frappe.utils.cint(pref.get("in_app_enabled", 1)))

		existing = frappe.db.get_value(
			"User Notification Preference",
			{"user": user, "team": team, "category": category},
			"name",
		)
		if existing:
			frappe.db.set_value(
				"User Notification Preference", existing,
				{"email_enabled": int(email), "in_app_enabled": int(in_app)},
			)
			name = existing
		else:
			doc = frappe.get_doc({
				"doctype": "User Notification Preference",
				"user": user,
				"team": team,
				"category": category,
				"email_enabled": int(email),
				"in_app_enabled": int(in_app),
			}).insert(ignore_permissions=True)
			name = doc.name

		saved.append({"category": category, "email_enabled": email, "in_app_enabled": in_app, "name": name})

	return {"saved": True, "preferences": saved}


@frappe.whitelist()
def get_user_preferences(team: str) -> dict:
	"""Return the calling user's notification preferences for *team*."""
	user = frappe.session.user
	rows = frappe.get_all(
		"User Notification Preference",
		filters={"user": user, "team": team},
		fields=["category", "email_enabled", "in_app_enabled"],
	)
	return {"preferences": rows}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def report_pilot_event(
	event_type: str,
	message: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	context: dict | None = None,
) -> dict:
	"""Inbound event from a Pilot instance (authenticated via X-Pilot-Token).

	Delegates to the notification engine. The team is resolved from the
	authenticated pilot credential — never from the request body.
	"""
	team = frappe.local.pilot_credential.team
	from central.notification.engine import dispatch

	return dispatch(
		team,
		event_type,
		message=message,
		context=context,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
	)
