# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Account-scope dashboard endpoints: identity, billing profile/settings, the
team header, and trust-tier progress.
"""

import frappe

from central.billing import authz
from central.billing.api.dashboard._shared import (
	_default_team,
	_has_money_activity,
	_missing_profile_fields,
	_profile_complete,
	_resolve_team,
	_team_clusters,
	_team_currency,
	_team_resource_count,
)

@frappe.whitelist()
def whoami() -> dict:
	"""Smoke endpoint: who the SPA is talking as, and their team scope."""
	return {
		"user": frappe.session.user,
		"team": _default_team(),
		"is_operator": authz.is_operator(),
	}


@frappe.whitelist()
def get_billing_profile(team: str | None = None) -> dict:
	"""The team's billing profile, plus the derived setup state the dashboard
	gates on:

	- `complete` — required fields (currency + legal name + address) all filled;
	  the gate for top-ups / buying credits / adding a payment method.
	- `missing` — required fields still blank.
	- `currency_locked` — true once a wallet credit, payment method, or invoice
	  exists, so the UI disables the currency picker.
	- `supported_currencies` — the allowed set (gateway-backed; not stored on the
	  profile).

	The stored fields (currency, legal name, address, GSTIN, …) come straight off
	the doc for the edit forms; the derived fields drive routing and locking.
	"""
	from central.billing.gateways.registry import supported_currencies

	team = _resolve_team(team)
	profile = (
		frappe.get_doc("Billing Profile", team).as_dict()
		if frappe.db.exists("Billing Profile", team)
		else {"team": team}
	)
	missing = _missing_profile_fields(team)
	profile.update({
		"complete": not missing,
		"missing": missing,
		"currency_locked": _has_money_activity(team),
		"supported_currencies": supported_currencies(),
	})
	return profile


@frappe.whitelist()
def get_billing_geo() -> dict:
	"""Dropdown feeds for the billing-address form: the full country list, and
	India's GST states (the single source of truth the Billing Profile validates
	the GSTIN against)."""
	from central.billing.india_gst import india_state_options

	return {
		"countries": frappe.get_all("Country", pluck="name", order_by="name asc"),
		"india_states": india_state_options(),
	}


def _validate_currency(team: str, currency: str | None):
	"""Currency must be gateway-supported, and is locked once money has moved."""
	if not currency:
		return
	from central.billing.gateways.registry import supported_currencies

	supported = supported_currencies()
	if currency not in supported:
		frappe.throw(
			f"{currency} is not a supported billing currency. "
			f"Choose one of: {', '.join(supported) or 'none configured'}.",
			frappe.ValidationError,
		)
	current = frappe.db.get_value("Billing Profile", team, "currency")
	if current and current != currency and _has_money_activity(team):
		frappe.throw(
			f"Billing currency is locked to {current}: this team already has a wallet, "
			"payment method, or invoice, so it can't be changed.",
			frappe.ValidationError,
		)


@frappe.whitelist(methods=["POST"])
def save_billing_profile(team: str | None = None, **fields) -> dict:
	"""Create/update the team's billing identity: currency, legal name, address,
	GSTIN (validated in the controller). Currency is constrained to gateway-
	supported values and locked once the team has money activity."""
	team = _resolve_team(team, authz.MANAGE)
	allowed = ("currency", "legal_name", "email", "phone", "gstin", "address_line1",
			   "address_line2", "city", "state", "country", "pincode")
	values = {k: v for k, v in fields.items() if k in allowed}
	_validate_currency(team, values.get("currency"))

	from central.billing.payments import profile
	profile = profile.create_or_update_billing_profile(team, **values)
	
	return {"saved": True, "team": team, "gstin": profile.gstin, "currency": profile.currency,
			"setup_complete": _profile_complete(team)}


@frappe.whitelist()
def get_billing_settings(team: str | None = None) -> dict:
	"""Alert thresholds. (Payment mode was removed — billing is credits-first-then-
	card for every team, so there is no prepaid/postpaid switch.)"""
	team = _resolve_team(team)
	if not frappe.db.exists("Billing Profile", team):
		return {"team": team, "min_balance": 0, "spend_alert_threshold": 0}
	p = frappe.get_doc("Billing Profile", team)
	return {"team": team, "min_balance": p.min_balance,
			"spend_alert_threshold": p.spend_alert_threshold}


@frappe.whitelist(methods=["POST"])
def save_billing_settings(team: str | None = None, min_balance: float | None = None,
						  spend_alert_threshold: float | None = None) -> dict:
	"""Update the low-balance / spend alert thresholds."""
	team = _resolve_team(team, authz.MANAGE)
	if frappe.db.exists("Billing Profile", team):
		doc = frappe.get_doc("Billing Profile", team)
	else:
		doc = frappe.get_doc({"doctype": "Billing Profile", "team": team})
	if min_balance is not None:
		doc.min_balance = frappe.utils.flt(min_balance)
	if spend_alert_threshold is not None:
		doc.spend_alert_threshold = frappe.utils.flt(spend_alert_threshold)
	doc.save(ignore_permissions=True)
	return {"saved": True}


@frappe.whitelist()
def get_collection_status(team: str | None = None) -> dict:
	"""Collection mode + the "Action Required" banner feed (ADR 0005, #50).

	Re-checks an e-mandate team against the ₹15,000 silent-debit threshold using the
	month-to-date forecast (so we warn before the bill lands), then returns the state
	the banner renders from: the mode, whether action is required and why, the
	threshold, and the numbers (projected total, wallet balance, shortfall)."""
	team = _resolve_team(team)
	from central.billing.payments import collection_mode
	from central.billing.api.dashboard.invoices import get_forecast
	from central.billing.revenue import credits

	projected = frappe.utils.flt(get_forecast(team).get("projected_total"))
	st = collection_mode.evaluate(team, projected_amount=projected)
	wallet = frappe.utils.flt(credits.get_balance(team)["balance"])
	return {**st, "projected_total": projected, "wallet_balance": wallet,
			"shortfall": max(0.0, frappe.utils.flt(projected - wallet, 2)),
			"currency": _team_currency(team)}


@frappe.whitelist(methods=["POST"])
def set_collection_mode(team: str | None = None, mode: str | None = None) -> dict:
	"""Customer resolves Action Required (or switches) — manual_checkout / prepaid."""
	team = _resolve_team(team, authz.MANAGE)
	from central.billing.payments import collection_mode

	return collection_mode.choose(team, mode)


@frappe.whitelist()
def get_team_overview(team: str | None = None) -> dict:
	"""Team header: trust tier, account standing, payment mode, resource count."""
	from central.billing.catalog import entitlements

	team = _resolve_team(team)
	caps = entitlements.get_team_caps(team)
	standing = frappe.db.get_value("Subscription", {"team": team}, "account_standing") or "Current"
	resources = _team_resource_count(team)
	clusters = len(_team_clusters(team))
	currency = _team_currency(team)
	# Caps resolve live from the team's tier level × its currency — no FX.
	return {"team": team, "tier": caps.tier,
			"max_spend": frappe.utils.flt(caps.max_spend),
			"standing": standing, "resources": resources, "clusters": clusters,
			"currency": currency}


@frappe.whitelist()
def get_trust_tier(team: str | None = None) -> dict:
	"""What the team's trust tier offers, and how to reach the next level.

	Returns the current tier's limits (spend cap in billing currency, resource
	cap), the team's progress (resources used, paid invoices, cumulative paid),
	and the NEXT tier's promotion criteria — so a customer can see what unlocks
	more headroom.
	"""
	from central.billing.catalog import entitlements

	team = _resolve_team(team)
	currency = _team_currency(team)
	current_tier = entitlements.get_team_caps(team).tier

	# The ladder carries per-currency thresholds; everything below reads the row
	# for THIS team's currency, so caps are native (no FX conversion).
	levels = entitlements.get_ladder()
	current_seq = next((l.sequence for l in levels if l.tier == current_tier), None)
	current = next((l for l in levels if l.tier == current_tier), None)
	nxt = next((l for l in levels if current_seq is not None and l.sequence == current_seq + 1), None)

	# Progress signals toward the next level. A team bills in one currency, so its
	# paid invoices are already in that currency — sum them directly.
	resources_used = _team_resource_count(team)
	paid_invoices = frappe.db.count("Invoice", {"team": team, "status": "Paid", "invoice_type": "Billable"})
	paid_rows = frappe.get_all("Invoice", {"team": team, "status": "Paid", "invoice_type": "Billable"},
							   ["amount_paid"])
	cumulative_paid = sum(frappe.utils.flt(r.amount_paid) for r in paid_rows)

	def level_view(l):
		if not l:
			return None
		row = entitlements.threshold_for(l, currency)
		return {
			"tier": l.tier, "sequence": l.sequence,
			"max_spend": frappe.utils.flt(row.max_spend) if row else None,
			"max_resource_count": l.max_resource_count,
			"min_paid_invoices": l.min_paid_invoices,
			"min_cumulative_paid": frappe.utils.flt(row.min_cumulative_paid) if row else None,
		}

	return {
		"team": team, "currency": currency,
		"current": level_view(current),
		"next": level_view(nxt),
		"is_top_tier": nxt is None,
		"progress": {
			"resources_used": resources_used,
			"paid_invoices": paid_invoices,
			"cumulative_paid": frappe.utils.flt(cumulative_paid),
		},
		"all_levels": [level_view(l) for l in levels],
	}


@frappe.whitelist()
def list_switchable_teams() -> list[dict]:
	"""POC team switcher — teams that have billing data, with their tier/standing."""
	teams = sorted(t for t in set(frappe.get_all("Subscription", pluck="team"))
				   | set(frappe.get_all("Billing Profile", pluck="team")) if t)
	out = []
	for t in teams:
		out.append({"team": t, "tier": frappe.db.get_value("Billing Profile", t, "trust_tier"),
					"standing": frappe.db.get_value("Subscription", {"team": t}, "account_standing") or "Current"})
	return out


# ── Notifications (#20) ──────────────────────────────────────────────────────
# The team's billing notification feed and per-event-type delivery preferences.
# The feed is the Billing Notification Log (what we actually sent or suppressed);
# preferences toggle which event types reach the team.

_NOTIFY_PREFS = (
	"notify_payment_success", "notify_payment_failure", "notify_payment_retry",
	"notify_invoice_overdue", "notify_credit_low", "notify_card_expiry",
	"notify_mandate_reauth", "notify_trial_expiring",
)


@frappe.whitelist()
def list_notifications(team: str | None = None, limit: int = 50) -> list[dict]:
	"""Recent billing notifications sent to (or suppressed for) the team."""
	team = _resolve_team(team)
	return frappe.get_all(
		"Billing Notification Log",
		filters={"team": team},
		fields=["name", "event_type", "channel", "status", "subject", "message",
				"reference_doctype", "reference_name", "sent_at"],
		order_by="sent_at desc",
		limit=limit,
	)


@frappe.whitelist()
def get_notification_preferences(team: str | None = None) -> dict:
	"""Per-event-type delivery toggles. Absent = everything on by default."""
	team = _resolve_team(team)
	prefs = {p: 1 for p in _NOTIFY_PREFS}
	if frappe.db.exists("Notification Preference", team):
		doc = frappe.get_doc("Notification Preference", team)
		prefs = {p: int(doc.get(p) or 0) for p in _NOTIFY_PREFS}
	prefs["team"] = team
	return prefs


@frappe.whitelist(methods=["POST"])
def save_notification_preferences(team: str | None = None, **prefs) -> dict:
	"""Update which event types notify the team (billing:manage)."""
	team = _resolve_team(team, authz.MANAGE)
	values = {p: int(frappe.utils.cint(prefs.get(p))) for p in _NOTIFY_PREFS if p in prefs}
	if frappe.db.exists("Notification Preference", team):
		doc = frappe.get_doc("Notification Preference", team)
		doc.update(values)
	else:
		doc = frappe.get_doc({"doctype": "Notification Preference", "team": team, **values})
	doc.save(ignore_permissions=True)
	return {"saved": True, "team": team}
