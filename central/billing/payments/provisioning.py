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

from central.billing import settings


def provision_billing_profile(team: str) -> None:
	"""Assign the entry tier, a tax profile, and welcome credits for `team`.

	Idempotent and best-effort per step; call it after a billing profile is
	created/updated."""
	assign_entry_tier(team)
	ensure_tax_profile(team)
	grant_welcome_credits(team)


def provision_signup_billing(team: str, country: str | None) -> None:
	"""Seed a brand-new team's billing at signup from its IP-derived `country`.

	Stamps a minimal Billing Profile with the country and the currency it implies
	(India → INR, everything else → USD), then runs the standard provisioning so
	the team gets its entry tier, tax profile, and welcome credits in that currency
	right away — no waiting for the full address.

	The profile is created with `ignore_mandatory`: at signup we only know the
	country, and the legal name / address are filled in later from the dashboard.
	Idempotent — an existing profile (e.g. one already carrying money) is left
	untouched, and every downstream step is individually guarded."""
	from central.billing.api.dashboard._shared import currency_for_country
	from central.billing.india_gst import INDIA

	if not frappe.db.exists("Billing Profile", team):
		# When the IP can't be geolocated — localhost/127.0.0.1, a private address,
		# or a failed lookup — fall back to India, our home market. Currency is then
		# always derived from the country actually stamped on the profile, so the
		# two can never disagree (India → INR, everywhere else → USD).
		profile = frappe.get_doc({"doctype": "Billing Profile", "team": team})
		profile.country = country or INDIA
		profile.currency = currency_for_country(profile.country)
		profile.insert(ignore_permissions=True, ignore_mandatory=True)

	provision_billing_profile(team)
	complete_trial_billing_profile(team)


# Placeholder billing details for a staging-trial team, so its profile clears the
# completeness gate (the console blocks server creation until the profile is complete)
# without the user filling the form. Staging only — never a real customer's data.
_STAGING_TRIAL_PROFILE = {
	"legal_name": "Staging Trial",
	"address_line1": "Staging — no address on file",
	"city": "Staging",
}


def complete_trial_billing_profile(team: str) -> None:
	"""Fill a staging-trial team's Billing Profile with placeholder legal/address details
	so it passes the completeness gate. Idempotent: only blank required fields are set,
	the currency/country stamped at signup are kept, and a team that isn't a staging
	trial (or has no profile yet) is left untouched — signup creates the profile with the
	IP-derived currency first, then calls this."""
	from central.billing.india_gst import INDIA

	if not frappe.db.get_value("Team", team, "is_staging_trial"):
		return
	if not frappe.db.exists("Billing Profile", team):
		return
	profile = frappe.get_doc("Billing Profile", team)
	dirty = False
	for field, value in {**_STAGING_TRIAL_PROFILE, "country": profile.country or INDIA}.items():
		if not str(profile.get(field) or "").strip():
			profile.set(field, value)
			dirty = True
	if dirty:
		profile.save(ignore_permissions=True)


def on_team_update(doc, method: str | None = None) -> None:
	"""Keep a staging-trial team's billing profile complete, so it can create servers
	without the setup prompt. Fires on every Team save; a no-op for non-trial teams and
	when the profile is already complete."""
	complete_trial_billing_profile(doc.name)


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

	India is GST at the rate on Billing Settings; everywhere else ships an untaxed
	profile (output tax None) — a real row an admin can edit, rather than the
	implicit no-profile default."""
	if frappe.db.exists("Tax Profile", team):
		return

	profile = (
		frappe.db.get_value("Billing Profile", team, ["country", "currency"], as_dict=True) or frappe._dict()
	)
	india = (profile.country or "").strip() == "India" or profile.currency == "INR"
	values = (
		{"output_tax_type": "GST", "output_tax_rate": settings.default_gst_rate()}
		if india
		else {"output_tax_type": "None", "output_tax_rate": 0}
	)
	frappe.get_doc({"doctype": "Tax Profile", "team": team, **values}).insert(ignore_permissions=True)
	india = (profile.country or "").strip() == "India" or profile.currency == "INR"
	values = (
		{"output_tax_type": "GST", "output_tax_rate": 18}
		if india
		else {"output_tax_type": "None", "output_tax_rate": 0}
	)
	frappe.get_doc({"doctype": "Tax Profile", "team": team, **values}).insert(ignore_permissions=True)


def grant_welcome_credits(team: str) -> None:
	"""Grant the one-time welcome credits in the team's currency, if not already.

	Needs a currency (so the credit is booked in the right one) and grants only
	once — guarded on any prior Promotion entry for the team. The amount comes from
	Billing Settings, so it can be changed, or the grant switched off entirely,
	without a release; a currency with no configured amount gets no grant (rather
	than a wrong-currency one). What a team has already been granted is never
	revisited — the guard makes this a one-shot per team.
	"""
	currency = frappe.db.get_value("Billing Profile", team, "currency")
	if not currency:
		return
	amount = settings.welcome_credit_amount(currency)
	if not amount:
		return
	if frappe.db.exists("Credit Ledger Entry", {"team": team, "reference_type": "Promotion"}):
		return

	from central.billing.revenue import credits

	credits.grant_promotional_credits(team, amount, currency)
