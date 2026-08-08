# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Collection mode + the ₹15,000 "Action Required" threshold (issue #50, ADR 0005).

Billing is usage-based and variable. In India an *off-session* recurring debit
above ₹15,000 needs the customer to re-authenticate every cycle (an RBI rule), so
we auto-charge silently only while the bill stays under that line. The moment an
e-mandate team's bill (or its month-to-date forecast) crosses ₹15,000 we stop
trying to charge silently and flip the team to `action_required` — the account
keeps running until the customer picks `manual_checkout` (pay each invoice
on-session, any amount) or `prepaid` (fund the wallet).

This module is the pure state machine over `Billing Profile.collection_mode`; the
forecast number is supplied by the caller (the dashboard computes it in the authed
request, the charge loop passes the invoice total), so the logic stays unit-clean
and side-effect free apart from the profile write + one notification.
"""

import frappe
from frappe import _

from central.billing.payments import mandates

# RBI off-session silent-debit ceiling for our merchant category, in MAJOR units
# (₹). Compared against forecast / invoice totals, which the dashboard reports in
# major units. The adapter-level ceiling (paise) lives on RazorpayAdapter.
INR_SILENT_THRESHOLD = 15000

# The modes a customer may pick to resolve action_required (or switch into).
CUSTOMER_CHOOSABLE = ("Manual Checkout", "Prepaid")


def silent_threshold(team: str) -> float:
	"""The largest bill we may auto-charge silently: min(₹15,000, trust-tier cap).
	The tier cap is the real spend ceiling, so crossing it also trips action."""
	cap = frappe.utils.flt(mandates.team_cap(team))
	return float(min(INR_SILENT_THRESHOLD, cap)) if cap else float(INR_SILENT_THRESHOLD)


def evaluate(
	team: str, projected_amount: float | None = None, reason: str = "forecast_over_threshold"
) -> dict:
	"""Re-check an `emandate` team against the silent-debit threshold and trip
	`action_required` if `projected_amount` (₹, major units) crosses it. A no-op for
	any other mode (so it's safe to call from the charge loop / dashboard). Returns
	the current status()."""
	mode = frappe.db.get_value("Billing Profile", team, "collection_mode")
	if mode == "E-Mandate" and projected_amount is not None:
		if frappe.utils.flt(projected_amount) >= silent_threshold(team):
			trip(team, reason)
	return status(team)


def trip(team: str, reason: str) -> None:
	"""Pause silent auto-charge and raise Action Required. Idempotent — notifies
	once (a team already in action_required is left as-is)."""
	profile = frappe.get_doc("Billing Profile", team)
	if profile.collection_mode == "Action Required":
		return
	profile.collection_mode = "Action Required"
	profile.collection_action_reason = reason
	profile.save(ignore_permissions=True)

	from central.billing.platform import notifications

	notifications.notify(
		team,
		"Action Required",
		context={"reason": reason, "threshold": silent_threshold(team)},
		reference_doctype="Billing Profile",
		reference_name=team,
	)


def choose(team: str, mode: str) -> dict:
	"""Customer resolves action_required (or switches) to manual_checkout / prepaid.
	Reversible and idempotent; clears the action reason."""
	if mode not in CUSTOMER_CHOOSABLE:
		frappe.throw(_("Pick one of {0}.").format(', '.join(CUSTOMER_CHOOSABLE)), frappe.ValidationError)
	profile = frappe.get_doc("Billing Profile", team)
	profile.collection_mode = mode
	profile.collection_action_reason = None
	profile.save(ignore_permissions=True)
	return status(team)


def status(team: str) -> dict:
	"""The collection state for the Action Required banner / settings surface."""
	p = (
		frappe.db.get_value(
			"Billing Profile", team, ["collection_mode", "collection_action_reason"], as_dict=True
		)
		or frappe._dict()
	)
	mode = p.collection_mode or "Prepaid"
	return {
		"collection_mode": mode,
		"action_required": mode == "Action Required",
		"reason": p.collection_action_reason,
		"threshold": silent_threshold(team),
		"choices": list(CUSTOMER_CHOOSABLE),
	}
