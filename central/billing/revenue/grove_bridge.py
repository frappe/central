# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import datetime

import frappe

from central.billing.platform.jobs import each_isolated
from central.billing.revenue.usage_ledger import utc_today, write_days
from central.integrations.grove import GroveClient
from central.services.doctype.service.service import AI_METER, AI_SERVICE, NANO_PER_UNIT
from central.services.doctype.team_service.team_service import billed_subjects

# One Grove call per team and day, so a page of this many teams is a few minutes of work.
PAGE_SIZE = 200
LOGGED_FAILURES = 50
ONE_DAY = datetime.timedelta(days=1)


def read_ai_usage() -> int:
	"""Hourly, until Grove reports usage itself: read each AI team's cost that landed yesterday and today."""
	from central.billing.revenue.invoicing.run import billing_queue

	if not frappe.db.get_value("Service", AI_SERVICE, "central_reads"):
		return 0
	if not frappe.get_cached_doc("AI Settings").is_enrolled:
		return 0
	subscribe_ai_teams()
	today = utc_today()
	# A landing day is final once it ends, so only yesterday and today can still change.
	days = [str(today - ONE_DAY), str(today)]
	teams = sorted(billed_subjects(AI_SERVICE))
	for start in range(0, len(teams), PAGE_SIZE):
		frappe.enqueue(
			"central.billing.revenue.grove_bridge.read_page",
			queue=billing_queue(),
			teams=teams[start : start + PAGE_SIZE],
			days=days,
		)
	return len(teams)


def read_page(teams: list[str], days: list[str]) -> int:
	"""Read one page of AI teams' landing days and write them."""
	client = GroveClient.from_settings()
	meter = frappe.get_doc("Service", AI_SERVICE).get_meter(AI_METER)
	subjects = billed_subjects(AI_SERVICE, teams)
	rows, failed = [], []
	for team in teams:
		# One team's failure, of any kind, must not stop the page's other teams.
		try:
			for day in days:
				rows += landing_rows(client, subjects[team], meter, day)
		except Exception as error:
			failed.append(f"{team}: {error!r}")
	if failed:
		frappe.log_error(
			title=f"AI usage: {len(failed)} team(s) not read",
			message="\n".join(failed[:LOGGED_FAILURES]),
		)
	# A day another worker wrote meanwhile is written again by the next hour's reading.
	return write_days(rows).count


def landing_rows(client: GroveClient, team_service, meter, day: str) -> list[dict]:
	"""One Usage Day line per model of what Grove recorded for the team during a UTC day."""
	now = datetime.datetime.now(datetime.UTC)
	start = datetime.datetime.combine(frappe.utils.getdate(day), datetime.time(), datetime.UTC)
	until = min(start + ONE_DAY, now)
	usage = client.get_usage(
		[team_service.external_id], pulled_after=_rfc3339(start), pulled_until=_rfc3339(until)
	)
	as_of = frappe.utils.convert_utc_to_system_timezone(now).replace(tzinfo=None)
	return [
		meter.get_day_row(
			team_service,
			day,
			frappe.utils.flt(model["cost"]) * NANO_PER_UNIT,
			dimension=model["model"],
			source_amount=model["cost"],
			source_currency="USD",
			as_of=as_of,
		)
		for model in usage.get("model_summary") or []
	]


def subscribe_ai_teams() -> None:
	"""Subscribe every active AI team that has a billing currency and no subscription yet."""
	names = frappe.get_all(
		"Team Service",
		filters={"add_on_service": AI_SERVICE, "status": "Active", "subscription": ["is", "not set"]},
		pluck="name",
	)
	each_isolated("AI subscription", "Team Service", names, _subscribe)


def backfill(since: str, until: str | None = None) -> int:
	"""Store each AI team's landing days from `since` up to the day before billing starts, written off."""
	# Kept so the record outlives Grove's 90-day purge; days before Service.bill_from never bill.
	last = frappe.utils.getdate(until or frappe.db.get_value("Service", AI_SERVICE, "bill_from")) - ONE_DAY
	day, days = frappe.utils.getdate(since), []
	while day <= last:
		days.append(str(day))
		day += ONE_DAY
	teams = sorted(billed_subjects(AI_SERVICE))
	return sum(read_page(teams, days[start : start + 7]) for start in range(0, len(days), 7))


def _subscribe(name: str) -> None:
	service = frappe.get_doc("Team Service", name)
	service.subscribe_ai()
	if service.subscription:
		# A scheduled job with no user; Team Service is operator-only.
		service.save(ignore_permissions=True)


def _rfc3339(moment: datetime.datetime) -> str:
	return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
