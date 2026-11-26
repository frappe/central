# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Checks on services that push their usage: Central's own reading against the stored days, and silence.

They run only for a service whose `central_reads` is off; while Central reads a service itself there is
nothing to check. A check writes no day value: a difference is an operator alert.
"""

import datetime

import frappe
from frappe.query_builder import Case

from central.billing.revenue.grove_bridge import read_days
from central.billing.revenue.storage_bridge import (
	billed_buckets,
	bundled_bucket_reader,
	bundled_buckets_by_region,
	pages,
	team_bucket_reader,
)
from central.billing.revenue.usage_ledger import utc_today
from central.billing.revenue.usage_month import day_rows
from central.services.doctype.service.service import (
	AI_METER,
	AI_SERVICE,
	STORAGE_METER,
	STORAGE_SERVICE,
	is_read_by_central,
)
from central.services.doctype.team_service.team_service import billed_subjects

DOCTYPE = "Usage Check"
# A day's peak is at least any one reading of that day; below this share of Central's sample it is wrong.
STORAGE_TOLERANCE = 0.01
AI_TOLERANCE_USD = 0.01
KEPT_DAYS = 7
PAGE_SIZE = 100
# Checks updated per statement, so the statement stays small.
UPDATE_SIZE = 500
LOGGED_FAILURES = 50
CADENCE_HOURS = {"Hourly": 1, "Daily": 24}
_FIELDS = ["name", "creation", "modified", "owner", "modified_by"]


def sample_storage() -> int:
	"""Daily at 12:00 UTC: read every billed bucket once, to check the day's pushed peak tomorrow."""
	if is_read_by_central(STORAGE_SERVICE):
		return 0
	queued = 0
	for job, buckets in (
		("sample_team_page", billed_buckets()),
		("sample_bundled_page", bundled_buckets_by_region()),
	):
		for region, region_pages in pages(buckets).items():
			for page in region_pages:
				_enqueue(job, region=region, names=page)
				queued += len(page)
	return queued


def sample_team_page(region: str, names: list[str]) -> int:
	"""Read one page of a region's team buckets as billing would, and keep each reading."""
	return _sample(region, names, team_bucket_reader)


def sample_bundled_page(region: str, names: list[str]) -> int:
	"""Read one page of a region's backup buckets as billing would, and keep each reading."""
	return _sample(region, names, bundled_bucket_reader)


def _sample(region: str, names: list[str], reader) -> int:
	"""Read one page of buckets with the reader, and keep each reading for the check."""
	names, read = reader(names)
	now = frappe.utils.now_datetime()
	rows, failed = [], []
	for name in names:
		# One bucket's failure, of any kind, must not stop the page's other buckets.
		try:
			day = read(name)
		except Exception as error:
			failed.append(f"{name}: {error!r}")
			continue
		rows.append(
			_check(STORAGE_SERVICE, STORAGE_METER, day["subject"], "", day["day"], day["quantity"], now)
		)
	_log_failures(f"Usage check: {len(failed)} bucket(s) not sampled in {region}", failed)
	return _insert(rows)


def check_yesterday() -> None:
	"""Daily at 02:00 UTC: compare yesterday's stored days with Central's own reading, and prune."""
	day = utc_today() - datetime.timedelta(days=1)
	compare_storage(day)
	check_ai(day)
	prune_checks()


def compare_storage(day: datetime.date) -> int:
	"""Mark each of the day's storage samples whose stored peak is below it."""
	if is_read_by_central(STORAGE_SERVICE):
		return 0
	checks = frappe.get_all(
		DOCTYPE,
		filters={"service": STORAGE_SERVICE, "day": day, "checked_at": ["is", "not set"]},
		fields=["name", "subject", "read_value"],
	)
	peaks = _stored(STORAGE_SERVICE, day, [check.subject for check in checks])
	for start in range(0, len(checks), UPDATE_SIZE):
		_mark_checked(checks[start : start + UPDATE_SIZE], peaks)
	return len(checks)


def check_ai(day: datetime.date) -> int:
	"""Queue a read of Grove's landing day for every AI team, in pages."""
	if is_read_by_central(AI_SERVICE):
		return 0
	teams = sorted(billed_subjects(AI_SERVICE))
	for start in range(0, len(teams), PAGE_SIZE):
		_enqueue("check_ai_page", teams=teams[start : start + PAGE_SIZE], day=str(day))
	return len(teams)


def check_ai_page(teams: list[str], day: str) -> int:
	"""Compare each team's stored AI days with what Grove recorded that landing day, per model."""
	subjects = billed_subjects(AI_SERVICE, teams)
	read = read_days(subjects, {team: [day] for team in subjects}, "Usage check: {n} AI team(s) not read")
	grove: dict = {}
	for row in read.rows:
		key = (row["subject"], row["dimension"])
		grove[key] = grove.get(key, 0.0) + row["quantity"]
	stored = _stored(AI_SERVICE, day, list(subjects))
	now = frappe.utils.now_datetime()
	# A team Grove could not answer for is logged by the read and left unchecked.
	return _insert([row for team in read.teams for row in _ai_checks(team, day, grove, stored, now)])


def prune_checks(today=None) -> int:
	"""Delete checks older than the days kept."""
	cutoff = (today or utc_today()) - datetime.timedelta(days=KEPT_DAYS)
	names = frappe.get_all(DOCTYPE, filters={"day": ["<", cutoff]}, pluck="name")
	if names:
		frappe.db.delete(DOCTYPE, {"name": ["in", names]})
	return len(names)


def silent_services() -> list[dict]:
	"""A service that pushes its usage has sent no report for twice its expected cadence.
	Its days are not reaching Central, so they bill estimates or nothing until it reports again."""
	now = frappe.utils.now_datetime()
	services = frappe.get_all(
		"Service",
		filters={"enabled": 1, "central_reads": 0},
		fields=["name", "expected_cadence", "last_report_at"],
	)
	alerts = []
	for service in services:
		cadence = service.expected_cadence or "Hourly"
		if _is_silent(service.last_report_at, cadence, now):
			alerts.append(
				{
					"alert": "silent_service",
					"doctype": "Service",
					"subject": service.name,
					"team": None,
					"detail": _silence_detail(service.last_report_at, cadence),
				}
			)
	return alerts


def usage_mismatches() -> list[dict]:
	"""A pushed day differs from Central's own reading of the service by more than the tolerance.
	The invoice bills the pushed day; turn the service's Central Reads Usage on to read it again."""
	# A check left from before Central read the service again is not a difference any more.
	pushed = frappe.get_all("Service", filters={"central_reads": 0}, pluck="name")
	if not pushed:
		return []
	cutoff = utc_today() - datetime.timedelta(days=KEPT_DAYS)
	checks = frappe.get_all(
		DOCTYPE,
		filters={"is_mismatch": 1, "day": [">=", cutoff], "service": ["in", pushed]},
		fields=["name", "service", "meter", "subject", "dimension", "day", "read_value", "stored_value"],
		order_by="day desc",
		limit=100,
	)
	units = _meter_units(pushed)
	return [
		{
			"alert": "usage_mismatch",
			"doctype": DOCTYPE,
			"subject": check.name,
			"team": None,
			"detail": _mismatch_detail(check, units.get((check.service, check.meter))),
		}
		for check in checks
	]


def _is_silent(last_report_at, cadence: str, now: datetime.datetime) -> bool:
	window = datetime.timedelta(hours=2 * CADENCE_HOURS[cadence])
	return not last_report_at or last_report_at < now - window


def _silence_detail(last_report_at, cadence: str) -> str:
	if not last_report_at:
		return f"No report since Central stopped reading it (expected {cadence})"
	return f"Last report {last_report_at} ({frappe.utils.get_system_timezone()}) (expected {cadence})"


def _mismatch_detail(check, unit: str | None) -> str:
	named = " ".join(part for part in (check.service, check.subject, check.dimension) if part)
	return (
		f"{named} on {check.day} (UTC): Central read {_amount(check.read_value, unit)}, "
		f"the day holds {_amount(check.stored_value, unit)}"
	)


def _amount(value: float, unit: str | None) -> str:
	return f"{value:g} {unit}" if unit else f"{value:g}"


def _meter_units(services: list[str]) -> dict:
	"""The unit of each meter of the services, by service and meter."""
	meters = frappe.get_all(
		"Service Meter",
		filters={"parenttype": "Service", "parent": ["in", services]},
		fields=["parent", "meter_key", "unit"],
	)
	return {(meter.parent, meter.meter_key): meter.unit for meter in meters}


def _ai_checks(team: str, day: str, grove: dict, stored: dict, now) -> list[dict]:
	"""One check per model Grove or the ledger has for the team that day."""
	models = {model for subject, model in grove.keys() | stored.keys() if subject == team}
	rows = []
	for model in sorted(models):
		read, kept = grove.get((team, model), 0.0), stored.get((team, model), 0.0)
		row = _check(AI_SERVICE, AI_METER, team, model, day, read, now)
		row.update(stored_value=kept, checked_at=now, is_mismatch=abs(read - kept) > AI_TOLERANCE_USD)
		rows.append(row)
	return rows


def _mark_checked(checks: list, peaks: dict) -> None:
	"""Store each check's peak and outcome in one statement."""
	table = frappe.qb.DocType(DOCTYPE)
	stored_value, is_mismatch = Case(), Case()
	for check in checks:
		# A day with no row is readiness M1's to flag; here it is only compared when it exists.
		stored = peaks.get((check.subject, ""))
		is_low = stored is not None and stored < check.read_value * (1 - STORAGE_TOLERANCE)
		stored_value = stored_value.when(table.name == check.name, stored or 0)
		is_mismatch = is_mismatch.when(table.name == check.name, int(is_low))
	(
		frappe.qb.update(table)
		.set(table.stored_value, stored_value)
		.set(table.is_mismatch, is_mismatch)
		.set(table.checked_at, frappe.utils.now_datetime())
		.where(table.name.isin([check.name for check in checks]))
	).run()


def _stored(service: str, day, subjects: list[str]) -> dict:
	"""The stored quantity of each subject and dimension on a day."""
	if not subjects:
		return {}
	rows = day_rows({"service": service, "subject": ["in", subjects]}, day=day)
	return {(row.subject, row.dimension or ""): row.quantity for row in rows}


def _check(service: str, meter: str, subject: str, dimension: str, day, value: float, now) -> dict:
	return {
		"service": service,
		"meter": meter,
		"subject": subject,
		"dimension": dimension,
		"day": day,
		"read_value": value,
		"read_at": now,
		"stored_value": 0.0,
		"checked_at": None,
		"is_mismatch": 0,
	}


def _insert(rows: list[dict]) -> int:
	"""Insert checks; a day already sampled or checked keeps its first row."""
	if not rows:
		return 0
	now, user = frappe.utils.now_datetime(), frappe.session.user
	columns = list(rows[0])
	values = [(frappe.generate_hash(length=12), now, now, user, user, *row.values()) for row in rows]
	frappe.db.bulk_insert(DOCTYPE, _FIELDS + columns, values, ignore_duplicates=True)
	return len(rows)


def _enqueue(method: str, **kwargs) -> None:
	from central.billing.revenue.invoicing.run import billing_queue

	frappe.enqueue(f"central.billing.revenue.usage_checks.{method}", queue=billing_queue(), **kwargs)


def _log_failures(title: str, failed: list[str]) -> None:
	if failed:
		frappe.log_error(title=title, message="\n".join(failed[:LOGGED_FAILURES]))
