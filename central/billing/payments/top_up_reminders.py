# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Top-up reminders for INR bills a saved card or UPI cannot pay (issue #191).

A card or UPI may pay off-session only up to the team's off-session limit. When the
next bill, less the wallet, is above it, the team is asked to add the shortfall to its
wallet 5 and 2 days before the payment date, and the billing page shows the same ask.
Nothing here moves money or changes the limit.
"""

import math

import frappe

from central.billing.doctype.billing_profile.billing_profile import DEFAULT_PAYMENT_DAY, get_payment_date
from central.billing.doctype.invoice.invoice import owed_filters
from central.billing.platform import notifications
from central.billing.platform.jobs import each_isolated

EVENT = "Top-up Reminder"
REMINDER_DAYS = (5, 2)
ROUND_TO = 100
PAGE_SIZE = 500
# An empty mode reads as Prepaid (collection_mode.status).
REMINDED_MODES = ("Prepaid", "Auto Charge", "", None)


def run_top_up_reminders() -> int:
	"""Daily: queue one job per page of teams whose payment date is 5 or 2 days away."""
	from central.billing.revenue.invoicing.run import billing_queue

	today = frappe.utils.getdate()
	teams = sorted(get_due_teams(today))
	pages = 0
	for start in range(0, len(teams), PAGE_SIZE):
		page = teams[start : start + PAGE_SIZE]
		frappe.enqueue(
			"central.billing.payments.top_up_reminders.remind_team_page",
			queue=billing_queue(),
			job_id=f"top-up-reminder::{today}::{page[-1]}",
			deduplicate=True,
			teams=page,
			today=str(today),
		)
		pages += 1
	return pages


def remind_team_page(teams: list[str], today: str) -> list[dict]:
	"""Remind one page of teams, so one bad team never stops the rest."""
	return each_isolated("Top-up reminder", "Billing Profile", teams, lambda team: remind_team(team, today))


def remind_team(team: str, today) -> dict:
	"""Send one team its reminder when its bill is due in 5 or 2 days and the wallet is short."""
	today = frappe.utils.getdate(today)
	due = get_top_up_due(team, today)
	if not due or frappe.utils.getdate(due["date"]) not in reminder_dates(today):
		return {"team": team, "skipped": "not_due"}
	if not is_first_notice_today(team, today):
		return {"team": team, "skipped": "already_reminded"}
	send_top_up_notice(team, due)
	return {"team": team, "reminded": True}


def get_top_up_due(team: str, today=None, forecast: float | None = None) -> dict | None:
	"""What the team should add to its wallet before its next payment date, or None.

	`forecast` is this month's projected bill when the caller already has it."""
	if not is_reminded_team(team):
		return None
	today = frappe.utils.getdate(today)
	amount, date, invoice = get_next_bill(team, today, forecast)
	return get_shortfall_due(team, amount, date, invoice)


def get_shortfall_due(team: str, shortfall: float, date, invoice: str | None = None) -> dict | None:
	"""The top-up ask for a bill of `shortfall` after the wallet, or None when the card or
	UPI may pay it. A team with no saved method has a limit of 0."""
	from central.billing.payments import collection, collection_mode

	has_method = bool(collection.get_methods_left(team, invoice))
	limit = collection_mode.off_session_limit(team, invoice) if has_method else 0.0
	shortfall = frappe.utils.flt(shortfall, 2)
	if collection_mode.is_within_limit(limit, shortfall):
		return None
	return {
		"amount": math.ceil(shortfall / ROUND_TO) * ROUND_TO,
		"date": str(date),
		"limit": limit,
		"has_method": has_method,
		"invoice": invoice,
	}


def send_top_up_notice(team: str, due: dict) -> dict:
	"""Email and in-app notice asking the team to add `due["amount"]` to its wallet."""
	from central.billing.payments.payment_notices import format_date

	currency = "INR"
	return notifications.notify(
		team,
		EVENT,
		context={
			"amount": frappe.utils.fmt_money(due["amount"], currency=currency),
			"payment_date": format_date(due["date"]),
			"limit": frappe.utils.fmt_money(due["limit"], currency=currency) if due["has_method"] else None,
			"topup": int(due["amount"]),
		},
		reference_doctype="Invoice" if due.get("invoice") else None,
		reference_name=due.get("invoice"),
	)


def is_reminded_team(team: str) -> bool:
	"""INR teams whose card or UPI pays after the wallet: Prepaid and Auto Charge."""
	profile = frappe.db.get_value("Billing Profile", team, ["currency", "collection_mode"], as_dict=True)
	return bool(profile) and profile.currency == "INR" and profile.collection_mode in REMINDED_MODES


def is_first_notice_today(team: str, today) -> bool:
	"""Whether the team has had no top-up notice today. The profile row lock makes two
	runs wait for each other, so only one of them sends."""
	profile = frappe.qb.DocType("Billing Profile")
	frappe.qb.from_(profile).select(profile.name).where(profile.name == team).for_update().run()
	return not frappe.db.exists(
		"Billing Notification Log",
		{"team": team, "event_type": EVENT, "creation": [">=", frappe.utils.getdate(today)]},
	)


def reminder_dates(today) -> list:
	return [frappe.utils.getdate(frappe.utils.add_days(today, days)) for days in REMINDER_DAYS]


def get_next_bill(team: str, today, forecast: float | None = None) -> tuple[float, object, str | None]:
	"""The next bill after the wallet, its payment date, and its invoice once issued.

	An issued invoice not yet charged is that bill. Before the run issues it, the bill is
	this month's forecast, paid on the team's payment date next month."""
	from central.billing.revenue import credits

	wallet = frappe.utils.flt(credits.get_balance(team, "INR")["balance"])
	invoice = _get_uncharged_invoice(team, today)
	if invoice:
		return frappe.utils.flt(invoice.expected_collection) - wallet, invoice.payment_date, invoice.name
	if forecast is None:
		forecast = get_forecast_total(team, today)
	next_month = frappe.utils.add_months(frappe.utils.get_first_day(today), 1)
	return frappe.utils.flt(forecast) - wallet, get_payment_date(team, next_month), None


def get_forecast_total(team: str, today) -> float:
	"""This month's projected bill, tax included: the figure the dashboard forecast shows."""
	from central.billing.projection import engine

	# Unguarded like the dashboard forecast: a job may hold the reminder's own writes.
	projection = engine.project(
		team,
		frappe.utils.get_first_day(today),
		frappe.utils.get_last_day(today),
		today=today,
		mode="Optimistic",
		guarded=False,
	)
	return frappe.utils.flt((projection["invoice"] or {}).get("total"))


def get_due_teams(today) -> set[str]:
	"""Teams that may owe a reminder today, read without a forecast: an INR team on a
	reminded mode whose payment day is 5 or 2 days away, or whose issued bill is charged then."""
	dates = reminder_dates(today)
	return _teams_by_payment_day(dates) | _teams_by_invoice(dates)


def _teams_by_payment_day(dates: list) -> set[str]:
	days = {date.day for date in dates}
	# A profile with no payment day is charged on the default day.
	if DEFAULT_PAYMENT_DAY in days:
		days.add(0)
	profiles = frappe.get_all(
		"Billing Profile",
		filters={"currency": "INR", "payment_day": ["in", list(days)]},
		fields=["team", "collection_mode"],
	)
	return {row.team for row in profiles if row.collection_mode in REMINDED_MODES}


def _teams_by_invoice(dates: list) -> set[str]:
	return set(
		frappe.get_all(
			"Invoice",
			filters=[
				*owed_filters(),
				["invoice_type", "=", "Billable"],
				["currency", "=", "INR"],
				["expected_collection", ">", 0],
				["payment_date", "in", dates],
			],
			pluck="team",
			distinct=True,
		)
	)


def _get_uncharged_invoice(team: str, today):
	"""The team's issued invoice whose payment date has not passed, earliest first."""
	rows = frappe.get_all(
		"Invoice",
		filters=[
			*owed_filters(),
			["team", "=", team],
			["invoice_type", "=", "Billable"],
			["expected_collection", ">", 0],
			["payment_date", ">=", today],
		],
		fields=["name", "expected_collection", "payment_date"],
		order_by="payment_date asc",
		limit=1,
	)
	return rows[0] if rows else None
