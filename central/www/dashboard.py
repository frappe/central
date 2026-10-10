from __future__ import annotations

import frappe
from frappe.core.api.file import get_max_file_size
from frappe.sessions import get_csrf_token

from central.iam import get_user_team_names
from central.identity.doctype.team_invitation.team_invitation import get_expiry_days

no_cache = 1


def get_context(context):
	"""Boot data for the console's auth pages and dashboard. The build injects each key into
	`window`, and frappe-ui sends `window.csrf_token` with every write."""
	context.no_cache = 1
	# init_context() already set context.boot via get_website_settings()
	# (lang, sysdefaults, assets_json, etc.). Extend it rather than replace so
	# those framework defaults survive alongside the SPA's auth essentials.
	boot = context.boot or frappe._dict()
	boot["csrf_token"] = get_csrf_token()
	boot["user_type"] = getattr(frappe.session.data, "user_type", None)
	boot["features"] = frappe.get_cached_doc("Central Settings").feature_flags()
	boot["invitation_expiry_days"] = get_expiry_days()
	boot.update(build_auth_context())
	# Development benches expose Socket.IO directly; production proxies it.
	if frappe.conf.developer_mode:
		boot["socketio_port"] = frappe.conf.socketio_port
	boot["site_name"] = frappe.local.site
	boot["max_file_size"] = get_max_file_size()
	# Frappe stores datetimes as a naive clock in this zone. The dashboard parses
	# them here, then shows the viewer's local time. Asia/Calcutta is the old name
	# for Asia/Kolkata, and browsers do not know the old one.
	zone = frappe.utils.get_system_timezone()
	boot["system_timezone"] = "Asia/Kolkata" if zone == "Asia/Calcutta" else zone
	context.boot = boot

	return context


# Page-boot auth context — these are dashboard page-load concerns (not an HTTP API),
# so they live here beside get_context rather than in central.api.auth.


def build_auth_context() -> dict:
	return {
		"user": frappe.session.user or "Guest",
		"onboarding_complete": _onboarding_complete(),
	}


def _onboarding_complete() -> bool:
	"""True once the user's team completed a site login handoff — the signal the SPA uses to keep a
	brand-new user inside the onboarding funnel (and let a returning one skip it).
	A first-run user (no team or no site yet) is still onboarding."""
	user = frappe.session.user
	if not user or user == "Guest":
		return False
	teams = get_user_team_names(user)
	if not teams:
		return False

	return bool(
		frappe.get_list(
			"Site",
			filters={"team": ["in", teams], "claimed_at": ["is", "set"]},
			pluck="name",
			limit=1,
		)
	)
