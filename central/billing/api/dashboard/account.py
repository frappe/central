# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Account-scope dashboard endpoints: identity, billing profile/settings, the
team header, and trust-tier progress.
"""

import frappe

from central.billing.platform.security import is_billing_admin
from central.billing.api.dashboard._shared import (
	_FX_TO_INR,
	_default_team,
	_from_inr,
	_resolve_team,
	_team_clusters,
	_team_currency,
)


@frappe.whitelist()
def whoami() -> dict:
	"""Smoke endpoint: who the SPA is talking as, and their team scope."""
	return {
		"user": frappe.session.user,
		"team": _default_team(),
		"is_billing_admin": is_billing_admin(),
	}


@frappe.whitelist()
def get_billing_profile(team: str | None = None) -> dict:
	team = _resolve_team(team)
	if not frappe.db.exists("Billing Profile", team):
		return {"team": team}
	return frappe.get_doc("Billing Profile", team).as_dict()


@frappe.whitelist()
def save_billing_profile(team: str | None = None, **fields) -> dict:
	"""Create/update the team's billing identity (GSTIN validated in the controller)."""
	team = _resolve_team(team)
	allowed = ("legal_name", "email", "phone", "gstin", "address_line1", "address_line2",
			   "city", "state", "country", "pincode")
	values = {k: v for k, v in fields.items() if k in allowed}
	if frappe.db.exists("Billing Profile", team):
		doc = frappe.get_doc("Billing Profile", team)
		doc.update(values)
	else:
		doc = frappe.get_doc({"doctype": "Billing Profile", "team": team, **values})
	doc.save(ignore_permissions=True)
	return {"saved": True, "team": team, "gstin": doc.gstin}


@frappe.whitelist()
def get_billing_settings(team: str | None = None) -> dict:
	"""Payment mode + thresholds (wireframe: Billing Settings)."""
	team = _resolve_team(team)
	if not frappe.db.exists("Billing Profile", team):
		return {"team": team, "billing_mode": "postpaid", "min_balance": 0, "spend_alert_threshold": 0}
	p = frappe.get_doc("Billing Profile", team)
	return {"team": team, "billing_mode": p.billing_mode or "postpaid",
			"min_balance": p.min_balance, "spend_alert_threshold": p.spend_alert_threshold}


@frappe.whitelist()
def save_billing_settings(team: str | None = None, billing_mode: str | None = None,
						  min_balance: float | None = None,
						  spend_alert_threshold: float | None = None) -> dict:
	"""Mode changes take effect next billing period (presentation toggle)."""
	team = _resolve_team(team)
	if frappe.db.exists("Billing Profile", team):
		doc = frappe.get_doc("Billing Profile", team)
	else:
		doc = frappe.get_doc({"doctype": "Billing Profile", "team": team, "legal_name": team})
	if billing_mode:
		doc.billing_mode = billing_mode
	if min_balance is not None:
		doc.min_balance = frappe.utils.flt(min_balance)
	if spend_alert_threshold is not None:
		doc.spend_alert_threshold = frappe.utils.flt(spend_alert_threshold)
	doc.save(ignore_permissions=True)
	return {"saved": True, "billing_mode": doc.billing_mode}


@frappe.whitelist()
def get_team_overview(team: str | None = None) -> dict:
	"""Team header: trust tier, account standing, payment mode, resource count."""
	team = _resolve_team(team)
	tier = frappe.db.get_value("Trust Tier", team, ["tier", "max_spend"], as_dict=True) or {}
	standing = frappe.db.get_value("Subscription", {"team": team}, "account_standing") or "current"
	mode = frappe.db.get_value("Billing Profile", team, "billing_mode") or "postpaid"
	resources = frappe.db.count("Price Lock", {"team": team, "ended_at": ["is", "not set"]})
	clusters = len(_team_clusters(team))
	currency = _team_currency(team)
	return {"team": team, "tier": tier.get("tier"),
			"max_spend": _from_inr(tier.get("max_spend"), currency),
			"standing": standing, "billing_mode": mode, "resources": resources, "clusters": clusters,
			"currency": currency}


@frappe.whitelist()
def get_trust_tier(team: str | None = None) -> dict:
	"""What the team's trust tier offers, and how to reach the next level.

	Returns the current tier's limits (spend cap in billing currency, resource
	cap), the team's progress (resources used, paid invoices, cumulative paid),
	and the NEXT tier's promotion criteria — so a customer can see what unlocks
	more headroom.
	"""
	team = _resolve_team(team)
	currency = _team_currency(team)
	tt = frappe.db.get_value("Trust Tier", team, ["tier", "level", "max_spend", "max_resource_count"], as_dict=True) or {}

	levels = frappe.get_all(
		"Trust Tier Level",
		fields=["name", "tier", "sequence", "max_spend", "max_resource_count",
				"min_paid_invoices", "min_cumulative_paid"],
		order_by="sequence asc",
	)
	current_seq = next((l.sequence for l in levels if l.tier == tt.get("tier")), None)
	current = next((l for l in levels if l.tier == tt.get("tier")), None)
	nxt = next((l for l in levels if current_seq is not None and l.sequence == current_seq + 1), None)

	# Progress signals toward the next level.
	resources_used = frappe.db.count("Price Lock", {"team": team, "ended_at": ["is", "not set"]})
	paid_invoices = frappe.db.count("Invoice", {"team": team, "status": "Paid", "invoice_type": "billable"})
	paid_rows = frappe.get_all("Invoice", {"team": team, "status": "Paid", "invoice_type": "billable"},
							   ["amount_paid", "currency"])
	cumulative_paid_inr = sum(frappe.utils.flt(r.amount_paid) * _FX_TO_INR.get(r.currency, 1.0) for r in paid_rows)

	def level_view(l):
		if not l:
			return None
		return {
			"tier": l.tier, "sequence": l.sequence,
			"max_spend": _from_inr(l.max_spend, currency),
			"max_resource_count": l.max_resource_count,
			"min_paid_invoices": l.min_paid_invoices,
			"min_cumulative_paid": _from_inr(l.min_cumulative_paid, currency),
		}

	return {
		"team": team, "currency": currency,
		"current": level_view(current),
		"next": level_view(nxt),
		"is_top_tier": nxt is None,
		"progress": {
			"resources_used": resources_used,
			"paid_invoices": paid_invoices,
			"cumulative_paid": _from_inr(cumulative_paid_inr, currency),
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
		out.append({"team": t, "tier": frappe.db.get_value("Trust Tier", t, "tier"),
					"standing": frappe.db.get_value("Subscription", {"team": t}, "account_standing") or "current"})
	return out
