# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe

AUDIT = "billing audit of 21 Oct 2026"


def execute():
	"""Repair the billing data the readiness checks now guard against."""
	# Book missing wallet credit first: waiving gives credit back, which a drifted wallet refuses.
	book_wallet_balances_missing_from_the_ledger()
	mark_staging_teams_internal()
	match_currency_to_country()
	pin_tiers_set_by_hand()


def mark_staging_teams_internal():
	"""On a site that does not create staging trials, a staging-trial team is one of ours."""
	from central.billing import settings
	from central.billing.payments.provisioning import ensure_tax_profile
	from central.billing.revenue.invoicing.lifecycle import settle_internal_teams

	if settings.provision_teams_as_trial():
		return
	for team in frappe.get_all("Team", filters={"is_staging_trial": 1}, pluck="name"):
		ensure_tax_profile(team)
		frappe.db.set_value(
			"Tax Profile",
			team,
			{"is_internal": 1, "internal_reason": f"Staging-trial team, marked by the {AUDIT}."},
		)
		frappe.db.set_value("Team", team, "is_staging_trial", 0)
	# set_value skips the Tax Profile hook that waives, so waive here, before any billing run.
	settle_internal_teams()


def match_currency_to_country():
	"""Bill a team in its country's currency, if nothing it holds is in another currency."""
	from central.billing.api.dashboard._shared import currency_for_country

	invoiced = set(frappe.get_all("Invoice", pluck="team", distinct=True))
	credited = set(
		frappe.get_all("Credit Ledger Entry", fields=["team", "currency"], distinct=True, as_list=True)
	)
	mandated = frappe.get_all(
		"Payment Method",
		filters={"status": ["!=", "Cancelled"], "mandate_currency": ["is", "set"]},
		fields=["team", "mandate_currency"],
		distinct=True,
		as_list=True,
	)
	for profile in frappe.get_all(
		"Billing Profile", filters={"country": ["is", "set"]}, fields=["name", "team", "country", "currency"]
	):
		wanted = currency_for_country(profile.country)
		has_money = profile.team in invoiced or (profile.team, profile.currency) in credited
		strands_a_method = any(team == profile.team and currency != wanted for team, currency in mandated)
		if profile.currency != wanted and not has_money and not strands_a_method:
			frappe.db.set_value("Billing Profile", profile.name, "currency", wanted)


def pin_tiers_set_by_hand():
	"""A tier above the entry rung with no recorded reason was set by hand: pin it and say so."""
	entry = frappe.db.get_value("Trust Tier Level", {"is_default": 1}, "name")
	tiers = dict(frappe.get_all("Trust Tier Level", fields=["name", "tier"], as_list=True))
	for profile in frappe.get_all(
		"Billing Profile",
		filters={"trust_tier_level": ["not in", ("", entry)], "promotion_basis": ["is", "not set"]},
		fields=["name", "trust_tier_level", "manual_override"],
	):
		frappe.db.set_value(
			"Billing Profile",
			profile.name,
			{
				"manual_override": 1,
				"trust_tier": tiers.get(profile.trust_tier_level),
				"promotion_basis": f"Set by hand with no reason; pinned by the {AUDIT}.",
				# A bespoke cap never applied to an unpinned tier, so pinning must not start applying it.
				**({} if profile.manual_override else {"override_max_spend": 0}),
			},
		)


def book_wallet_balances_missing_from_the_ledger():
	"""Book the credit a wallet holds that no ledger entry explains, so its credits can move again."""
	from central.billing.revenue.credits import promotional_expiry_date

	ledger = _ledger_balances()
	for wallet in frappe.get_all("Credit Wallet", fields=["name", "team", "currency", "balance"]):
		missing = frappe.utils.flt(
			frappe.utils.flt(wallet.balance) - ledger.get((wallet.team, wallet.currency), 0.0), 2
		)
		if missing <= 0.01:
			continue
		entry = frappe.get_doc(
			{
				"doctype": "Credit Ledger Entry",
				"team": wallet.team,
				"entry_type": "Credit",
				"amount": missing,
				"currency": wallet.currency,
				"running_balance": wallet.balance,
				"reference_type": "Promotion",
				"expires_on": promotional_expiry_date(),
				"note": f"Wallet balance with no ledger entry, booked by the {AUDIT}.",
				"created_at": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Credit Wallet", wallet.name, "last_entry", entry.name, update_modified=False)


def _ledger_balances() -> dict:
	"""What every (team, currency) ledger adds up to, in one query."""
	from frappe.query_builder import Case
	from frappe.query_builder.functions import Sum

	entry = frappe.qb.DocType("Credit Ledger Entry")
	signed = Case().when(entry.entry_type == "Credit", entry.amount).else_(-entry.amount)
	rows = (
		frappe.qb.from_(entry)
		.select(entry.team, entry.currency, Sum(signed))
		.groupby(entry.team, entry.currency)
		.run()
	)
	return {(team, currency): frappe.utils.flt(total) for team, currency, total in rows}
