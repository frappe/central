# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.query_builder.functions import Count

from central.billing import settings
from central.billing.catalog.entitlements import cap_for, get_ladder
from central.billing.catalog.subscriptions import active_segments
from central.billing.india_gst import INDIA
from central.billing.platform.invariants import Violation

STALLED_HOURS = 3

# The accounting fields every issued invoice needs. A blank one holds every invoice.
ACCOUNTING_FIELDS = (
	"company",
	"company_address",
	"advance_account",
	"income_account",
	"cost_center",
	"service_item",
	"in_state_template",
	"out_state_template",
)


def _internal_teams() -> set[str]:
	return set(frappe.get_all("Tax Profile", filters={"is_internal": 1}, pluck="team"))


def _profiles() -> dict:
	return {
		p.team: p
		for p in frappe.get_all(
			"Billing Profile",
			fields=[
				"team",
				"currency",
				"country",
				"legal_name",
				"address_line1",
				"city",
				"profile_id",
				"address_id",
				"contact_id",
				"collection_mode",
				"trust_tier_level",
				"trust_tier",
				"manual_override",
				"override_max_spend",
				"promotion_basis",
			],
		)
	}


def _billed_run_rates() -> dict[str, float]:
	"""Monthly run rate of every team the next run bills, internal teams left out."""
	internal = _internal_teams()
	rates: dict[str, float] = {}
	for segment in active_segments({"enabled": 1}):
		if segment.team not in internal:
			rates[segment.team] = rates.get(segment.team, 0.0) + frappe.utils.flt(segment.locked_rate)
	return rates


# --- billing profile ----------------------------------------------------------


def check_currency_matches_country() -> list[Violation]:
	"""India is billed only in INR, and only India in INR."""
	return [
		Violation(
			check="B1",
			team=p.team,
			currency=p.currency,
			subject_doctype="Billing Profile",
			subject=p.team,
			detail=f"Billed in {p.currency} with a billing address in {p.country}.",
		)
		for p in _profiles().values()
		if p.country and p.currency and (p.country == INDIA) != (p.currency == "INR")
	]


def check_mandates_in_billing_currency() -> list[Violation]:
	"""A live payment method is set up in the team's billing currency."""
	profiles = _profiles()
	return [
		Violation(
			check="B2",
			team=m.team,
			currency=m.mandate_currency,
			subject_doctype="Payment Method",
			subject=m.name,
			detail=f"Set up in {m.mandate_currency}, but the team is billed in {profiles[m.team].currency}.",
		)
		for m in frappe.get_all(
			"Payment Method",
			filters={"status": ["!=", "Cancelled"], "mandate_currency": ["is", "set"]},
			fields=["name", "team", "mandate_currency"],
		)
		if m.team in profiles and m.mandate_currency != profiles[m.team].currency
	]


def check_billed_teams_are_invoiceable() -> list[Violation]:
	"""A team the next run bills has full billing details and its accounting records."""
	from central.billing.ingester.connection import enabled

	profiles = _profiles()
	syncs = enabled()
	found = []
	for team in _billed_run_rates():
		profile = profiles.get(team)
		missing = [
			f
			for f in ("currency", "legal_name", "address_line1", "city", "country")
			if not (profile or {}).get(f)
		]
		unsynced = (
			syncs and profile and not (profile.profile_id and profile.address_id and profile.contact_id)
		)
		if missing or unsynced:
			found.append(
				Violation(
					check="B3",
					team=team,
					subject_doctype="Billing Profile",
					subject=team,
					detail=f"Its invoice will be held: missing {', '.join(missing)}."
					if missing
					else "Its invoice will be held: the team is not yet in the accounting system.",
				)
			)
	return found


def check_accounting_setup() -> list[Violation]:
	"""Billing Settings names every accounting record an issued invoice needs."""
	from central.billing.ingester.connection import enabled

	if not enabled() or not _billed_run_rates():
		return []
	values = frappe.get_cached_doc("Billing Settings")
	missing = [field for field in ACCOUNTING_FIELDS if not values.get(field)]
	if not values.receivable_accounts:
		missing.append("receivable_accounts")
	if not missing:
		return []
	return [
		Violation(
			check="B4",
			subject_doctype="Billing Settings",
			subject="Billing Settings",
			detail=f"Every invoice will be held until these are set: {', '.join(missing)}.",
		)
	]


# --- trust tier ---------------------------------------------------------------


def check_spend_within_tier() -> list[Violation]:
	"""A team's monthly run rate fits its trust-tier spend cap."""
	profiles = _profiles()
	ladder = {level.name: level for level in get_ladder()}
	found = []
	for team, rate in _billed_run_rates().items():
		profile = profiles.get(team)
		if not profile:
			continue
		cap = (profile.manual_override and profile.override_max_spend) or cap_for(
			ladder.get(profile.trust_tier_level) or {}, profile.currency
		)
		if rate > frappe.utils.flt(cap) + 0.01:
			found.append(
				Violation(
					check="T1",
					team=team,
					currency=profile.currency,
					subject_doctype="Billing Profile",
					subject=team,
					expected=frappe.utils.flt(cap),
					actual=rate,
					detail=f"Runs {rate} a month on a {profile.trust_tier_level or 'missing'} tier capped at {cap}.",
				)
			)
	return found


def check_servers_within_tier() -> list[Violation]:
	"""A team runs no more servers than its trust tier allows."""
	machine = frappe.qb.DocType("Virtual Machine")
	counts = dict(
		frappe.qb.from_(machine)
		.select(machine.team, Count("*"))
		.where(machine.status != "Terminated")
		.groupby(machine.team)
		.run()
	)
	profiles = _profiles()
	internal = _internal_teams()
	limits = {level.name: level.max_resource_count for level in get_ladder()}
	return [
		Violation(
			check="T2",
			team=team,
			subject_doctype="Billing Profile",
			subject=team,
			expected=limits.get(profiles[team].trust_tier_level, 0),
			actual=count,
			detail=f"Runs {count} servers on a tier that allows {limits.get(profiles[team].trust_tier_level, 0)}.",
		)
		for team, count in counts.items()
		if team in profiles
		and team not in internal
		and count > limits.get(profiles[team].trust_tier_level, 0)
	]


def check_tier_changes_are_recorded() -> list[Violation]:
	"""A tier above the entry rung was reached by the tier review or pinned with a reason."""
	entry = next((level.name for level in get_ladder() if level.is_default), None)
	found = []
	for p in _profiles().values():
		if not p.trust_tier_level or p.trust_tier_level == entry or p.promotion_basis:
			continue
		found.append(
			Violation(
				check="T3",
				team=p.team,
				subject_doctype="Billing Profile",
				subject=p.team,
				detail=f"On {p.trust_tier_level} with no recorded reason. Pin the tier and write why.",
			)
		)
	return found


# --- subscriptions and servers --------------------------------------------------


def check_subscriptions_are_priced() -> list[Violation]:
	"""Every running subscription has a price: a locked rate, or a metered plan with a rate."""
	from central.billing.catalog.pricing import get_catalog_rates, resolve_rate

	metered = set(frappe.get_all("Plan Category", filters={"billing_type": "Metered"}, pluck="name"))
	categories = dict(frappe.get_all("Plan", fields=["name", "category"], as_list=True))
	found = []
	for segment in active_segments({"enabled": 1}):
		if frappe.utils.flt(segment.locked_rate) > 0:
			continue
		if categories.get(segment.plan) in metered and resolve_rate(
			get_catalog_rates("Plan", segment.plan), segment.currency, segment.cluster
		):
			continue
		found.append(
			Violation(
				check="S1",
				team=segment.team,
				currency=segment.currency,
				subject_doctype="Subscription",
				subject=segment.subscription,
				detail=f"Plan {segment.plan} bills nothing: no locked rate and no metered rate in {segment.currency}.",
			)
		)
	return found


def check_running_servers_are_billed() -> list[Violation]:
	"""A running server has an active subscription, unless it is a free trial."""
	from central.signups.trial import is_billing_deferred

	billed = set(
		frappe.get_all("Subscription", filters={"enabled": 1, "server_id": ["is", "set"]}, pluck="server_id")
	)
	return [
		Violation(
			check="S2",
			team=vm.team,
			subject_doctype="Virtual Machine",
			subject=vm.name,
			detail="Running with no active subscription, so nothing bills it.",
		)
		for vm in frappe.get_all("Virtual Machine", filters={"status": "Running"}, fields=["name", "team"])
		if vm.name not in billed and not is_billing_deferred(vm.name)
	]


def check_terminated_servers_stop_billing() -> list[Violation]:
	"""A terminated server's subscription is closed."""
	subscription = frappe.qb.DocType("Subscription")
	machine = frappe.qb.DocType("Virtual Machine")
	rows = (
		frappe.qb.from_(subscription)
		.join(machine)
		.on(machine.name == subscription.server_id)
		.select(subscription.name, subscription.team)
		.where((subscription.enabled == 1) & (machine.status == "Terminated"))
		.run(as_dict=True)
	)
	return [
		Violation(
			check="S3",
			team=row.team,
			subject_doctype="Subscription",
			subject=row.name,
			detail="Still active on a terminated server, so it keeps billing.",
		)
		for row in rows
	]


def check_storage_usage_is_recorded() -> list[Violation]:
	"""Every storage subscription's usage was read in the last day, so the month bills in full."""
	from central.services.doctype.team_service.team_service import STORAGE_SERVICE

	today = frappe.utils.getdate()
	if today.day == 1:
		return []
	billed = set(
		frappe.get_all(
			"Team Service",
			filters={"add_on_service": STORAGE_SERVICE, "status": "Active", "subscription": ["is", "set"]},
			pluck="subscription",
		)
	)
	subjects = frappe.get_all(
		"Subscription", filters={"name": ["in", list(billed)]}, fields=["name", "team", "service_subject"]
	)
	read_through = dict(
		frappe.get_all(
			"Usage Rollup",
			filters={"resource_type": "Storage", "period_start": [">=", today.replace(day=1)]},
			fields=["resource_id", "sequence"],
			as_list=True,
		)
	)
	return [
		Violation(
			check="M1",
			team=s.team,
			subject_doctype="Subscription",
			subject=s.name,
			expected=today.day - 1,
			actual=frappe.utils.cint(read_through.get(s.service_subject)),
			detail="Storage usage has not been read for a day or more. The next reading bills the missed days at its level.",
		)
		for s in subjects
		if frappe.utils.cint(read_through.get(s.service_subject)) < today.day - 1
	]


# --- collection -------------------------------------------------------------------


def check_billed_teams_can_pay() -> list[Violation]:
	"""A team whose run rate its credit does not cover has a way to pay the rest."""
	profiles = _profiles()
	paying = set(frappe.get_all("Payment Method", filters={"status": "Active"}, pluck="team"))
	balances = {
		(w.team, w.currency): frappe.utils.flt(w.balance)
		for w in frappe.get_all("Credit Wallet", fields=["team", "currency", "balance"])
	}
	found = []
	for team, rate in _billed_run_rates().items():
		profile = profiles.get(team) or frappe._dict()
		balance = balances.get((team, profile.currency), 0.0)
		if rate <= balance or team in paying or profile.collection_mode == "Manual Checkout":
			continue
		found.append(
			Violation(
				check="W1",
				team=team,
				currency=profile.currency,
				subject_doctype="Billing Profile",
				subject=team,
				expected=rate,
				actual=balance,
				detail="Credit does not cover a month and the team has no payment method, so its invoice will go unpaid.",
			)
		)
	return found


def check_promotional_credit_expires() -> list[Violation]:
	"""Promotional credit carries an expiry date when the policy says it expires."""
	if not settings.promotional_credit_validity_days():
		return []
	internal = _internal_teams()
	return [
		Violation(
			check="W2",
			team=e.team,
			currency=e.currency,
			subject_doctype="Credit Ledger Entry",
			subject=e.name,
			actual=frappe.utils.flt(e.amount),
			detail="Promotional credit with no expiry date, so it never expires.",
		)
		for e in frappe.get_all(
			"Credit Ledger Entry",
			filters={
				"entry_type": "Credit",
				"paid_in": 0,
				"reference_type": "Promotion",
				"expires_on": ["is", "not set"],
			},
			fields=["name", "team", "currency", "amount"],
		)
		if e.team not in internal
	]


def check_no_staging_trials_outside_staging() -> list[Violation]:
	"""A team is a staging trial only on a site that creates them."""
	if settings.provision_teams_as_trial():
		return []
	return [
		Violation(
			check="X1",
			team=team,
			subject_doctype="Team",
			subject=team,
			detail="Marked as a staging trial on a site that does not create them: placeholder billing details, no tier.",
		)
		for team in frappe.get_all("Team", filters={"is_staging_trial": 1}, pluck="name")
	]


def check_regions_have_priced_metal() -> list[Violation]:
	"""A region that runs servers has active bare metal with a monthly cost, so its margin is known."""
	priced = set(
		frappe.get_all(
			"Metal Server", filters={"status": "Active", "cost_per_month_inr": [">", 0]}, pluck="region"
		)
	)
	regions = frappe.get_all(
		"Virtual Machine",
		filters={"status": ["not in", ("Terminated", "Failed")]},
		pluck="region",
		distinct=True,
	)
	return [
		Violation(
			check="R1",
			subject_doctype="Region",
			subject=region,
			detail="Runs servers but has no active Metal Server with a monthly cost, so unit economics read 0 cost.",
		)
		for region in regions
		if region not in priced
	]


def check_servers_have_a_known_host() -> list[Violation]:
	"""A live server in a region with bare metal has a host that one of its Metal Servers records."""
	hosts = {}
	for machine in frappe.get_all(
		"Metal Server", filters={"status": "Active"}, fields=["region", "atlas_host_id"]
	):
		hosts.setdefault(machine.region, set()).add(machine.atlas_host_id)

	servers = frappe.get_all(
		"Virtual Machine",
		filters={"status": ["not in", ("Terminated", "Failed")], "region": ["in", list(hosts)]},
		fields=["name", "region", "atlas_host_id"],
		order_by="name asc",
	)
	unplaced = {}
	for server in servers:
		if not server.atlas_host_id or server.atlas_host_id not in hosts[server.region]:
			unplaced.setdefault(server.region, []).append(server.name)
	# One row per region: a region with no linked machine would otherwise alert once per server.
	# The gap is the region's metal, not any one team's, so the row carries no team.
	return [
		Violation(
			check="R2",
			subject_doctype="Region",
			subject=region,
			actual=len(names),
			detail=_unplaced_detail(names),
		)
		for region, names in unplaced.items()
	]


def _unplaced_detail(names: list[str]) -> str:
	examples = ", ".join(names[:5])
	return f"{len(names)} server(s) run on no known Metal Server, so machine profitability leaves them out. For example: {examples}."


def check_billing_run_is_moving() -> list[Violation]:
	"""The closed month's run has started, and no draft it owes waits hours to be collected."""
	from central.billing.revenue.invoicing.run import billing_period

	_, period_end = billing_period()
	had_billing = frappe.db.exists("Subscription", {"start_date": ["<=", period_end]})
	if had_billing and not frappe.db.exists("Billing Run", str(period_end)):
		return [
			Violation(
				check="B5",
				subject_doctype="Billing Run",
				subject=str(period_end),
				detail="The monthly billing run for this month has not started.",
			)
		]

	run = frappe.db.get_value(
		"Billing Run", str(period_end), ["teams", "drafted", "started_at"], as_dict=True
	)
	stalled_since = frappe.utils.add_to_date(None, hours=-STALLED_HOURS)
	if run and run.teams and not run.drafted and run.started_at and run.started_at < stalled_since:
		return [
			Violation(
				check="B5",
				subject_doctype="Billing Run",
				subject=str(period_end),
				detail=f"The billing run started over {STALLED_HOURS} hours ago and has drafted no invoice. Run draft_monthly_invoices.",
			)
		]

	# The hourly sweep collects a draft within the hour; three hours means the run stopped.
	waiting = frappe.db.count(
		"Invoice",
		{
			"status": "Draft",
			"period_end": ["<=", period_end],
			"hold_reason": ["is", "not set"],
			"creation": ["<", stalled_since],
		},
	)
	if not waiting:
		return []
	return [
		Violation(
			check="B5",
			subject_doctype="Billing Run",
			subject=str(period_end),
			detail=f"{waiting} draft invoice(s) waited over {STALLED_HOURS} hours to be collected. Check the billing workers and the Error Log.",
			actual=waiting,
		)
	]


CHECKS = {
	"B1": ("Billing currency matches the country", check_currency_matches_country),
	"B2": ("Payment methods are in the billing currency", check_mandates_in_billing_currency),
	"B3": ("Billed teams can be invoiced", check_billed_teams_are_invoiceable),
	"B4": ("Accounting setup is complete", check_accounting_setup),
	"B5": ("The billing run is moving", check_billing_run_is_moving),
	"T1": ("Spend fits the trust tier", check_spend_within_tier),
	"T2": ("Servers fit the trust tier", check_servers_within_tier),
	"T3": ("Tier changes are recorded", check_tier_changes_are_recorded),
	"S1": ("Running subscriptions are priced", check_subscriptions_are_priced),
	"S2": ("Running servers are billed", check_running_servers_are_billed),
	"S3": ("Terminated servers stop billing", check_terminated_servers_stop_billing),
	"M1": ("Storage usage is read daily", check_storage_usage_is_recorded),
	"W1": ("Billed teams can pay", check_billed_teams_can_pay),
	"W2": ("Promotional credit expires", check_promotional_credit_expires),
	"X1": ("No staging trials outside staging", check_no_staging_trials_outside_staging),
	"R1": ("Regions with servers have priced bare metal", check_regions_have_priced_metal),
	"R2": ("Servers run on a known Metal Server", check_servers_have_a_known_host),
}
