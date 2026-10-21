from datetime import date

import frappe
from frappe.utils import add_days, getdate, today

from central.signups.affiliates.summary import (
	get_payments,
	get_teams_with_product_referral,
	is_converted,
)

CURVE_MONTHS = 12
TREND_MONTHS = 12


def get_affiliate_retention(affiliate: str) -> dict:
	"""How long the affiliate's paying customers keep paying. A customer is active in a period when
	it paid an invoice in it, and pays from its first paid invoice to its last."""
	# The affiliate holds no permission on these records, so every read filters on the affiliate.
	paid_days = get_customer_paid_days(affiliate)
	day = getdate(today())
	this_month = month_index(day)

	paid_months = {team: {month_index(paid) for paid in days} for team, days in paid_days.items()}
	first_paid = {team: min(months) for team, months in paid_months.items()}
	last_paid = {team: max(months) for team, months in paid_months.items()}

	return {
		"customers": len(paid_days),
		"active_30_days": count_active(paid_days, add_days(day, -30)),
		"active_90_days": count_active(paid_days, add_days(day, -90)),
		"trend": [
			sum(this_month - offset in months for months in paid_months.values())
			for offset in reversed(range(TREND_MONTHS))
		],
		"curve": get_curve(first_paid, last_paid, this_month),
	}


def count_active(paid_days: dict[str, list[date]], since: date) -> int:
	return sum(any(paid >= since for paid in days) for days in paid_days.values())


def get_customer_paid_days(affiliate: str) -> dict[str, list[date]]:
	"""The days each converted customer paid on, from its first referral by the affiliate."""
	referrals = frappe.get_all(
		"Product Referral",
		filters={"affiliate": affiliate},
		fields=["referred_team", "product", "creation"],
	)
	payments = get_payments({row.referred_team for row in referrals})
	product_teams = get_teams_with_product_referral(set(payments))

	referred_on = {}
	for row in referrals:
		if is_converted(row, payments, product_teams):
			team = row.referred_team
			referred_on[team] = min(referred_on.get(team, row.creation), row.creation)

	return {
		team: [getdate(paid) for paid in payments[team] if paid >= since]
		for team, since in referred_on.items()
	}


def get_curve(first_paid: dict[str, int], last_paid: dict[str, int], this_month: int) -> list[dict]:
	"""For month 1, 2, 3 and on: the share of customers still paying that many months after their
	first payment. A month counts once it is over, and only for customers whose first payment is
	that far back, so recent customers do not pull the line down."""
	curve = []
	for month in range(1, CURVE_MONTHS + 1):
		counted = [team for team, first in first_paid.items() if first + month < this_month]
		if not counted:
			break

		still_paying = sum(last_paid[team] >= first_paid[team] + month for team in counted)
		curve.append(
			{
				"month": month,
				"customers": len(counted),
				"still_paying": still_paying,
				"percent": round(100 * still_paying / len(counted)),
			}
		)

	return curve


def month_index(day: date) -> int:
	return day.year * 12 + day.month - 1
