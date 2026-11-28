# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import datetime
import hashlib
from zoneinfo import ZoneInfo

import frappe

from central.billing.platform.jobs import each_isolated
from central.billing.revenue.service_reports import MAXIMUM_DIMENSION
from central.billing.revenue.usage_ledger import (
	CentralLines,
	system_time,
	utc_stamp,
	utc_today,
	write_central_days,
)
from central.billing.revenue.usage_reports import READ_BY_CENTRAL, canonical_json
from central.integrations.grove import GroveClient
from central.services.doctype.service.service import (
	AI_METER,
	AI_SERVICE,
	NANO_PER_UNIT,
	is_read_by_central,
	is_read_by_central_locked,
)
from central.services.doctype.team_service.team_service import billed_subjects

# One Grove call per team and day, so a page of this many teams is a few minutes of work.
PAGE_SIZE = 200
LOGGED_FAILURES = 50
ONE_DAY = datetime.timedelta(days=1)
# A team further behind is caught up over the next hours, so one run stays bounded.
CATCH_UP_DAYS = 7
BACKFILL_PAGE_DAYS = 7


def read_ai_usage() -> int:
	"""Hourly, until Grove reports usage itself: read each AI team's cost per model and landing day."""
	from central.billing.revenue.invoicing.run import billing_queue

	if not is_read_by_central(AI_SERVICE):
		return 0
	if not frappe.get_cached_doc("AI Settings").is_enrolled:
		return 0
	subscribe_ai_teams()
	teams = sorted(billed_subjects(AI_SERVICE))
	for start in range(0, len(teams), PAGE_SIZE):
		frappe.enqueue(
			"central.billing.revenue.grove_bridge.read_page",
			queue=billing_queue(),
			teams=teams[start : start + PAGE_SIZE],
		)
	return len(teams)


def read_page(teams: list[str]) -> int:
	"""Read one page of AI teams from the day each was last read through today, and write them."""
	subjects = billed_subjects(AI_SERVICE, teams)
	bill_from = frappe.db.get_value("Service", AI_SERVICE, "bill_from")
	today = utc_today()
	plan = {team: _days_to_read(service, bill_from, today) for team, service in subjects.items()}
	read = read_days(subjects, {team: days for team, days in plan.items() if days})
	# The page may have been queued while Central still read AI usage; checked under the lock a
	# pushed report takes, so the two never both write a day.
	if not is_read_by_central_locked(AI_SERVICE):
		frappe.logger("billing").debug("AI usage page skipped: Grove reports its usage now")
		return 0
	written = write_central_days(read.rows).count
	# Only after its rows are written, so a team that failed is read again from the same day.
	_mark_read({subjects[team].name: plan[team][-1] for team in read.teams})
	return written


def read_days(
	subjects: dict, days: dict, failure_title: str = "AI usage: {n} team(s) not read"
) -> frappe._dict:
	"""Grove's landing days for each team, as day lines, and the teams read in full."""
	client = GroveClient.from_settings()
	meter = frappe.get_doc("Service", AI_SERVICE).get_meter(AI_METER)
	rows, read, failed = [], [], []
	for team, team_days in days.items():
		# One team's failure, of any kind, must not stop the page's other teams.
		try:
			team_rows = [row for day in team_days for row in landing_rows(client, subjects[team], meter, day)]
		except Exception as error:
			failed.append(f"{team}: {error!r}")
			continue
		rows += team_rows
		read.append(team)
	if failed:
		frappe.log_error(
			title=failure_title.format(n=len(failed)),
			message="\n".join(failed[:LOGGED_FAILURES]),
		)
	return frappe._dict(rows=rows, teams=read)


def landing_rows(client: GroveClient, team_service, meter, day: str) -> list[dict]:
	"""One day line per model of what Grove recorded for the team during a UTC day."""
	now = datetime.datetime.now(datetime.UTC)
	start = datetime.datetime.combine(frappe.utils.getdate(day), datetime.time(), datetime.UTC)
	until = min(start + ONE_DAY, now)
	usage = client.get_usage(
		[team_service.external_id], pulled_after=utc_stamp(start), pulled_until=utc_stamp(until)
	)
	as_of = system_time(now)
	models = usage.get("model_summary") or []
	# Fails the team rather than cutting the name: two cut names could merge and lose one model's cost.
	if too_long := [model["model"] for model in models if len(model["model"]) > MAXIMUM_DIMENSION]:
		raise ValueError(f"model name over {MAXIMUM_DIMENSION} characters: {too_long[0][:MAXIMUM_DIMENSION]}")
	return [
		meter.get_day_row(
			team_service,
			day,
			frappe.utils.flt(model["cost"]) * NANO_PER_UNIT,
			dimension=model["model"],
			source_amount=model["cost"],
			source_currency="USD",
			as_of=as_of,
			evidence=_read_evidence(model, start, until),
		)
		for model in models
	]


def _read_evidence(model: dict, start: datetime.datetime, until: datetime.datetime) -> dict:
	"""The landing window Central read from Grove, and a hash of what Grove answered for the model."""
	return {
		"v": 1,
		"read": "grove.usage",
		"window": [utc_stamp(start), utc_stamp(until)],
		"requests": frappe.utils.cint(model.get("requests")),
		"tokens": frappe.utils.cint(model.get("tokens")),
		"sha256": hashlib.sha256(canonical_json(model)).hexdigest(),
	}


def subscribe_ai_teams() -> None:
	"""Subscribe every active AI team that has a billing currency and no subscription yet."""
	names = frappe.get_all(
		"Team Service",
		filters={"add_on_service": AI_SERVICE, "status": "Active", "subscription": ["is", "not set"]},
		pluck="name",
	)
	each_isolated("AI subscription", "Team Service", names, _subscribe)


def backfill(since: str) -> int:
	"""Store each AI team's landing days from `since` up to the day before billing starts, written off."""
	# Kept so the record outlives Grove's 90-day purge; days before Service.bill_from never bill.
	last = frappe.utils.getdate(frappe.db.get_value("Service", AI_SERVICE, "bill_from")) - ONE_DAY
	days = _days(frappe.utils.getdate(since), last)
	subjects = billed_subjects(AI_SERVICE)
	lines = CentralLines(READ_BY_CENTRAL)
	written = 0
	for start in range(0, len(days), BACKFILL_PAGE_DAYS):
		page = days[start : start + BACKFILL_PAGE_DAYS]
		written += lines.write(read_days(subjects, {team: page for team in subjects}).rows).count
	lines.keep()
	return written


def _days_to_read(team_service, bill_from, today: datetime.date) -> list[str]:
	"""From the day the team was last read, or first billed, through today, at most CATCH_UP_DAYS."""
	first = team_service.usage_read_until
	if not first:
		started = _utc_day(team_service.creation)
		first = max(started, frappe.utils.getdate(bill_from)) if bill_from else started
	first = frappe.utils.getdate(first)
	return _days(first, min(today, first + (CATCH_UP_DAYS - 1) * ONE_DAY))


def _days(first: datetime.date, last: datetime.date) -> list[str]:
	return [str(first + offset * ONE_DAY) for offset in range((last - first).days + 1)]


def _mark_read(last_days: dict) -> None:
	"""Keep the last day read of each team service, where its next reading starts."""
	by_day: dict = {}
	for name, day in last_days.items():
		by_day.setdefault(day, []).append(name)
	service = frappe.qb.DocType("Team Service")
	for day, names in by_day.items():
		frappe.qb.update(service).set(service.usage_read_until, day).where(service.name.isin(names)).run()


def _subscribe(name: str) -> None:
	service = frappe.get_doc("Team Service", name)
	service.subscribe_ai()
	if service.subscription:
		# A scheduled job with no user; Team Service is operator-only.
		service.save(ignore_permissions=True)


def _utc_day(moment: datetime.datetime) -> datetime.date:
	"""The UTC day of a system-time moment."""
	zone = ZoneInfo(frappe.utils.get_system_timezone())
	return frappe.utils.get_datetime(moment).replace(tzinfo=zone).astimezone(datetime.UTC).date()
