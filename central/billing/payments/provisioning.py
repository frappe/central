# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""One-time provisioning when a team completes its billing profile.

Setting up a billing profile is the moment a team becomes a real paying customer,
so three things are wired up here, once, off that event:

  - the entry Trust Tier (the ladder rung every team starts on, so its caps resolve);
  - a Tax Profile (GST for India, untaxed elsewhere at launch);
  - a welcome grant of promotional credits.

Each step is independently idempotent and guarded, so this is safe to re-run on
every save of the profile — a step that has already happened (tier linked, tax
profile exists, credits granted) is skipped.
"""

import frappe

# Welcome credits granted once, in the team's own billing currency. A currency we
# don't list gets no grant (rather than a wrong-currency one).
WELCOME_CREDITS = {"INR": 1000.0, "USD": 15.0, "EUR": 15.0}


def provision_billing_profile(team: str) -> None:
	"""Assign the entry tier, a tax profile, and welcome credits for `team`.

	Idempotent and best-effort per step; call it after a billing profile is
	created/updated."""
	assign_entry_tier(team)
	ensure_tax_profile(team)
	grant_welcome_credits(team)


def assign_entry_tier(team: str) -> None:
	"""Link the entry Trust Tier Level on the profile if it has none yet.

	Skips a team that's already tiered or manually pinned. Without this a fresh
	team has no linked level, so get_team_caps returns no ceiling (tier=None)."""
	profile = frappe.get_doc("Billing Profile", team)
	if profile.trust_tier_level or profile.manual_override:
		return

	from central.billing.catalog import entitlements

	entry = entitlements.entry_level()
	if not entry:
		return  # no ladder seeded — nothing to assign
	profile.trust_tier_level = entry.name
	profile.trust_tier = entry.tier
	profile.save(ignore_permissions=True)


def ensure_tax_profile(team: str) -> None:
	"""Create the team's Tax Profile if absent.

	India is GST at 18% (the launch default output tax); everywhere else ships an
	untaxed profile (output tax None) — a real row an admin can edit, rather than
	the implicit no-profile default."""
	if frappe.db.exists("Tax Profile", team):
		return

	profile = frappe.db.get_value(
		"Billing Profile", team, ["country", "currency"], as_dict=True
	) or frappe._dict()
	india = (profile.country or "").strip() == "India" or profile.currency == "INR"
	values = {"output_tax_type": "GST", "output_tax_rate": 18} if india else {
		"output_tax_type": "None", "output_tax_rate": 0
	}
	frappe.get_doc({"doctype": "Tax Profile", "team": team, **values}).insert(
		ignore_permissions=True
	)


def grant_welcome_credits(team: str) -> None:
	"""Grant the one-time welcome credits in the team's currency, if not already.

	Needs a currency (so the credit is booked in the right one) and grants only
	once — guarded on any prior Promotion entry for the team."""
	currency = frappe.db.get_value("Billing Profile", team, "currency")
	if not currency:
		return
	amount = WELCOME_CREDITS.get(currency)
	if not amount:
		return
	if frappe.db.exists("Credit Ledger Entry", {"team": team, "reference_type": "Promotion"}):
		return

	from central.billing.revenue import credits

	credits.grant_promotional_credits(team, amount, currency)
