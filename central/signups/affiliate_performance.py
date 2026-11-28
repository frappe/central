from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime

import frappe
from frappe import _
from frappe.query_builder.functions import Max
from frappe.utils import add_days, get_datetime, getdate, now_datetime

from central.signups.affiliate_link import get_post_url

PERIOD_DAYS = {"30d": 30, "90d": 90, "12m": 365, "all": None}
# A team that paid an invoice this recently still pays. Invoices are monthly, so 35 days
# leaves room for a late payment.
STILL_PAYING_DAYS = 35
# The product filter value and label for a team that signed up without a product.
FRAPPE_CLOUD = "frappe-cloud"


def get_performance(affiliate: str, period: str, product: str | None = None) -> dict:
	"""Counts for the teams the affiliate referred in the period, and the period before it.
	Team names never leave this function."""
	if period not in PERIOD_DAYS:
		frappe.throw(_("Choose a period from the list."))

	end = now_datetime()
	days = PERIOD_DAYS[period]
	start = add_days(end, -days) if days else None
	teams = get_referred_teams(affiliate, start, end, product)
	steps = get_steps({team.name for team in teams})
	previous = get_referred_teams(affiliate, add_days(start, -days), start, product) if start else None

	return {
		"totals": get_totals(teams, steps, previous),
		"funnel": get_funnel(teams, steps),
		"weekly": get_weekly(teams, steps, start, end),
		# A team without a source groups under None, which the console names Direct.
		"by_source": group(teams, steps, lambda team: team.utm_source or None, "source"),
		"by_product": group(teams, steps, lambda team: team.product_title, "product"),
		"campaigns": get_campaigns(teams, steps),
	}


def get_referred_teams(
	affiliate: str, start: datetime | None, end: datetime, product: str | None
) -> list[frappe._dict]:
	"""The affiliate's teams created in the dates, with their link values and product."""
	# The affiliate holds no permission on these teams, so every read filters on the affiliate.
	team = frappe.qb.DocType("Team")
	query = (
		frappe.qb.from_(team)
		.select(
			team.name,
			team.creation,
			team.utm_source,
			team.utm_campaign,
			team.utm_content,
			team.landing_product,
		)
		.where((team.affiliate == affiliate) & (team.creation < end))
	)
	if start:
		query = query.where(team.creation >= start)

	teams = query.run(as_dict=True)
	set_products(teams)
	if product:
		wanted = None if product == FRAPPE_CLOUD else product
		teams = [row for row in teams if row.product == wanted]
	return teams


def set_products(teams: list[frappe._dict]) -> None:
	"""Each team's product: the one its first trial site was made for, else the one in its
	signup link, else none, which reads as Frappe Cloud. It only groups the team: the affiliate
	is credited when the team is created, whatever product it starts."""
	site_products = {}
	if teams:
		for site in frappe.get_all(
			"Site",
			filters={"team": ["in", [row.name for row in teams]], "product": ["is", "set"]},
			fields=["team", "product"],
			order_by="creation asc",
		):
			site_products.setdefault(site.team, site.product)

	titles = dict(frappe.get_all("Product", fields=["name", "title"], as_list=True))
	for row in teams:
		row.product = site_products.get(row.name) or row.landing_product
		row.product_title = titles.get(row.product, row.product) if row.product else _("Frappe Cloud")


def get_steps(teams: set[str]) -> dict[str, set[str]]:
	"""The teams that reached each step. A later step implies the earlier ones."""
	if not teams:
		return {"started": set(), "card": set(), "paying": set(), "still_paying": set()}

	payments = get_last_payments(teams)
	paying = set(payments)
	card = paying | set(
		frappe.get_all(
			"Payment Method",
			filters={"team": ["in", list(teams)], "status": "Active"},
			pluck="team",
			distinct=True,
		)
	)
	since = add_days(now_datetime(), -STILL_PAYING_DAYS)
	return {
		"started": card | set(frappe.get_all("Site", filters={"team": ["in", list(teams)]}, pluck="team")),
		"card": card,
		"paying": paying,
		"still_paying": {team for team, paid_at in payments.items() if get_datetime(paid_at) >= since},
	}


def get_last_payments(teams: set[str]) -> dict[str, datetime]:
	"""When each team last paid a billable invoice that took real money."""
	invoice = frappe.qb.DocType("Invoice")
	rows = (
		frappe.qb.from_(invoice)
		.select(invoice.team, Max(invoice.paid_at).as_("paid_at"))
		.where(
			invoice.team.isin(list(teams))
			& (invoice.status == "Paid")
			& (invoice.invoice_type == "Billable")
			& (invoice.amount_paid > 0)
			& invoice.paid_at.isnotnull()
		)
		.groupby(invoice.team)
	).run(as_dict=True)
	return {row.team: row.paid_at for row in rows}


def get_totals(teams: list, steps: dict, previous: list | None) -> dict:
	previous_paying = None
	if previous is not None:
		previous_paying = len(get_steps({team.name for team in previous})["paying"])

	return {
		"signups": len(teams),
		"paying": len(steps["paying"]),
		"still_paying": len(steps["still_paying"]),
		"still_paying_days": STILL_PAYING_DAYS,
		"previous_signups": len(previous) if previous is not None else None,
		"previous_paying": previous_paying,
	}


def get_funnel(teams: list, steps: dict) -> dict:
	return {
		"signed_up": len(teams),
		"started_site": len(steps["started"]),
		"added_card": len(steps["card"]),
		"paying": len(steps["paying"]),
		"waiting_to_pay": len(steps["card"] - steps["paying"]),
	}


def get_weekly(teams: list, steps: dict, start: datetime | None, end: datetime) -> list[dict]:
	"""Signups and paying customers by the week the team signed up, with 0 for a quiet week."""
	signups, paying = defaultdict(int), defaultdict(int)
	for team in teams:
		week = week_start(team.creation)
		signups[week] += 1
		paying[week] += team.name in steps["paying"]

	first = week_start(start) if start else min(signups, default=week_start(end))
	weeks, week = [], first
	while week <= week_start(end):
		weeks.append({"week": str(week), "signups": signups[week], "paying": paying[week]})
		week = add_days(week, 7)
	return weeks


def get_campaigns(teams: list, steps: dict) -> list[dict]:
	"""Each campaign with its source and product, sorted by paying customers."""
	rows = group(
		teams,
		steps,
		lambda team: (team.utm_campaign, team.utm_source or None, team.product_title),
		"key",
	)
	# The console makes the post a link, so only an http or https URL leaves this function.
	post_urls = {
		(team.utm_campaign, team.utm_source or None, team.product_title): url
		for team in sorted(teams, key=lambda team: team.creation)
		if (url := get_post_url(team.utm_content))
	}
	campaigns = [
		{
			"campaign": row["key"][0],
			"source": row["key"][1],
			"product": row["key"][2],
			"signups": row["signups"],
			"paying": row["paying"],
			"post_url": post_urls.get(row["key"]),
		}
		for row in rows
	]
	return sorted(campaigns, key=lambda row: (row["paying"], row["signups"]), reverse=True)


def group(
	teams: list[frappe._dict],
	steps: dict[str, set[str]],
	key: Callable[[frappe._dict], object],
	label: str,
) -> list[dict]:
	"""Signups and paying customers for each value of `key`, most signups first."""
	signups, paying = defaultdict(int), defaultdict(int)
	for team in teams:
		value = key(team)
		signups[value] += 1
		paying[value] += team.name in steps["paying"]

	rows = [{label: value, "signups": signups[value], "paying": paying[value]} for value in signups]
	return sorted(rows, key=lambda row: (row["signups"], row["paying"]), reverse=True)


def week_start(moment: datetime | date) -> date:
	day = getdate(moment)
	return add_days(day, -day.weekday())
