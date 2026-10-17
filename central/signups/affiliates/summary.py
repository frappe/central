from collections import defaultdict
from datetime import date, datetime

import frappe
from frappe import _
from frappe.query_builder import Order
from frappe.query_builder.functions import Count, Date
from frappe.utils import add_days, get_datetime, getdate

NONE_LABEL = "(none)"
# The dates a summary may span. Each day is a row, and the period before is read as well.
MAX_SUMMARY_DAYS = 366
# Each step counts the referrals that reached it. A later step implies the earlier ones, so a
# team that paid counts as having added billing and created a site.
STEPS = ("visited", "signed_up", "created_site", "added_billing", "converted")


def get_affiliate_summary(affiliate: str, from_date: str | date, to_date: str | date) -> dict:
	"""The funnel of one affiliate for the dates, both included, and the same numbers for the period
	of the same length just before. Visits count by their creation, and signups and later steps by
	the referral's creation. Team names never leave this function."""
	# The affiliate holds no permission on these records, so every read filters on the affiliate.
	start, end = getdate(from_date), add_days(getdate(to_date), 1)
	if start >= end:
		frappe.throw(_("The start date must not be after the end date."))
	if (end - start).days > MAX_SUMMARY_DAYS:
		frappe.throw(_("Choose a period of at most {0} days.").format(MAX_SUMMARY_DAYS))

	visits = get_visit_counts(affiliate, start, end)
	referrals = get_referral_rows(affiliate, start, end)
	rows = visits + referrals
	previous_start = add_days(start, -(end - start).days)

	return {
		"totals": count(rows),
		"previous_totals": count(
			get_visit_counts(affiliate, previous_start, start)
			+ get_referral_rows(affiliate, previous_start, start)
		),
		"daily": get_daily(visits, referrals, start, end),
		"by_link": group(rows, "link", "link"),
		"by_source": group(rows, "utm_source", "source"),
		"by_product": group(rows, "product", "product"),
		"by_country": group(rows, "country", "country"),
	}


def get_visit_counts(affiliate: str, start: date, end: date) -> list[dict]:
	visit = frappe.qb.DocType("Affiliate Visit")
	day = Date(visit.creation)
	return (
		frappe.qb.from_(visit)
		.select(
			day.as_("day"),
			visit.link,
			visit.utm_source,
			visit.product,
			visit.country,
			Count("*").as_("visited"),
		)
		.where((visit.affiliate == affiliate) & (visit.creation >= start) & (visit.creation < end))
		.groupby(day, visit.link, visit.utm_source, visit.product, visit.country)
	).run(as_dict=True)


def get_referral_rows(affiliate: str, start: date, end: date) -> list[dict]:
	"""The affiliate's referrals in the dates, newest first, with the steps each team reached.
	The link and country come from the visit, which owns them."""
	referral = frappe.qb.DocType("Product Referral")
	visit = frappe.qb.DocType("Affiliate Visit")
	referrals = (
		frappe.qb.from_(referral)
		.left_join(visit)
		.on(visit.name == referral.visit)
		.select(
			referral.referred_team,
			referral.product,
			referral.utm_source,
			referral.creation,
			visit.link,
			visit.country,
		)
		.where((referral.affiliate == affiliate) & (referral.creation >= start) & (referral.creation < end))
		.orderby(referral.creation, order=Order.desc)
	).run(as_dict=True)

	mark_steps(referrals)
	return referrals


def mark_steps(referrals: list[dict]) -> None:
	teams = {row.referred_team for row in referrals}
	payments = get_payments(teams)
	product_teams = get_teams_with_product_referral(teams)
	billing_teams = get_teams_with_payment_method(teams)
	sites = get_team_sites(teams)

	for row in referrals:
		row.signed_up = 1
		row.converted = is_converted(row, payments, product_teams)
		row.added_billing = row.converted or row.referred_team in billing_teams
		has_site = (row.referred_team, row.product) in sites if row.product else row.referred_team in sites
		row.created_site = row.added_billing or has_site


def is_converted(referral: dict, payments: dict[str, list[datetime]], product_teams: set[str]) -> bool:
	"""A team converts when it pays after the referral, so a team that already paid is not credited
	for it. A team's payment belongs to its product referrals. A Frappe Cloud referral converts only
	when the team has no product referral from any affiliate."""
	referred_on = get_datetime(referral.creation)
	has_paid = any(paid >= referred_on for paid in payments.get(referral.referred_team, []))
	return has_paid and (bool(referral.product) or referral.referred_team not in product_teams)


def get_payments(teams: set[str]) -> dict[str, list[datetime]]:
	"""When each team paid a billable invoice that took real money. A refund does not undo it."""
	if not teams:
		return {}

	payments = defaultdict(list)
	for invoice in frappe.get_all("Invoice", filters=paid_invoice_filters(teams), fields=["team", "paid_at"]):
		payments[invoice.team].append(get_datetime(invoice.paid_at))

	return payments


def paid_invoice_filters(teams: set[str]) -> dict:
	return {
		"team": ["in", list(teams)],
		"status": "Paid",
		"invoice_type": "Billable",
		"amount_paid": [">", 0],
		"paid_at": ["is", "set"],
	}


def get_teams_with_product_referral(teams: set[str]) -> set[str]:
	if not teams:
		return set()

	return set(
		frappe.get_all(
			"Product Referral",
			filters={"referred_team": ["in", list(teams)], "product": ["is", "set"]},
			pluck="referred_team",
			distinct=True,
		)
	)


def get_teams_with_payment_method(teams: set[str]) -> set[str]:
	if not teams:
		return set()

	return set(
		frappe.get_all(
			"Payment Method",
			filters={"team": ["in", list(teams)], "status": "Active"},
			pluck="team",
			distinct=True,
		)
	)


def get_team_sites(teams: set[str]) -> set:
	"""Each team with a site, and each (team, product) pair, so one set answers both questions."""
	if not teams:
		return set()

	rows = frappe.get_all("Site", filters={"team": ["in", list(teams)]}, fields=["team", "product"])
	return {row.team for row in rows} | {(row.team, row.product) for row in rows if row.product}


def get_daily(visits: list[dict], referrals: list[dict], start: date, end: date) -> list[dict]:
	"""Clicks, signups and paying signups for every day in the dates, with 0 on a quiet day. A paying
	signup counts on the day it signed up."""
	clicks, signups, paying = defaultdict(int), defaultdict(int), defaultdict(int)
	for row in visits:
		clicks[getdate(row.day)] += row.visited
	for row in referrals:
		signups[getdate(row.creation)] += 1
		paying[getdate(row.creation)] += int(row.converted)

	days = [add_days(start, offset) for offset in range((end - start).days)]
	return [
		{"day": str(day), "clicks": clicks[day], "signups": signups[day], "paying": paying[day]}
		for day in days
	]


def count(rows: list[dict]) -> dict:
	return {step: sum(int(row.get(step) or 0) for row in rows) for step in STEPS}


def group(rows: list[dict], field: str, label: str) -> list[dict]:
	"""The funnel for each value of a field, largest first. An empty value reads "(none)"."""
	groups = defaultdict(list)
	for row in rows:
		groups[row[field] or NONE_LABEL].append(row)

	table = [{label: value, **count(group_rows)} for value, group_rows in groups.items()]
	return sorted(table, key=lambda row: (row["visited"], row["signed_up"]), reverse=True)
