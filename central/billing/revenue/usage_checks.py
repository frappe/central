# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Checks on services that push their usage: Central's own reading against the stored days, and silence.

They run only for a service whose `central_reads` is off; while Central reads a service itself there is
nothing to check. A check writes no Usage Day: a difference is an operator alert.
"""

import datetime

import frappe

from central.billing.revenue.bundled_buckets import billed_storage_subjects
from central.billing.revenue.grove_bridge import landing_rows
from central.billing.revenue.usage_ledger import utc_today
from central.integrations.grove import GroveClient
from central.integrations.object_storage import ObjectStorageClient, ObjectStorageNotFound
from central.services.doctype.service.service import AI_METER, AI_SERVICE, STORAGE_METER, STORAGE_SERVICE
from central.services.doctype.team_service.team_service import billed_subjects

DOCTYPE = "Usage Check"
# A day's peak is at least any one reading of that day; below this share of Central's sample it is wrong.
STORAGE_TOLERANCE = 0.01
AI_TOLERANCE_USD = 0.01
KEPT_DAYS = 7
PAGE_SIZE = 100
LOGGED_FAILURES = 50
CADENCE_HOURS = {"Hourly": 1, "Daily": 24}
_FIELDS = ["name", "creation", "modified", "owner", "modified_by"]


def sample_storage() -> int:
	"""Daily at 12:00 UTC: read every billed bucket once, to check the day's pushed peak tomorrow."""
	if is_read_by_central(STORAGE_SERVICE):
		return 0
	regions: dict[str, list[str]] = {}
	for name, bucket in billed_storage_subjects(day=utc_today()).items():
		regions.setdefault(bucket.region, []).append(name)
	for region, names in regions.items():
		for start in range(0, len(names), PAGE_SIZE):
			_enqueue("sample_storage_page", region=region, names=names[start : start + PAGE_SIZE])
	return sum(len(names) for names in regions.values())


def sample_storage_page(region: str, names: list[str]) -> int:
	"""Read one page of a region's buckets and keep each reading for today's check."""
	client = ObjectStorageClient.from_region(region)
	divisor = _divisor(STORAGE_SERVICE, STORAGE_METER)
	now, today = frappe.utils.now_datetime(), utc_today()
	rows, failed = [], []
	for name in names:
		# One bucket's failure, of any kind, must not stop the page's other buckets.
		try:
			used = _used_bytes(client, name)
		except Exception as error:
			failed.append(f"{name}: {error!r}")
			continue
		rows.append(_check(STORAGE_SERVICE, STORAGE_METER, name, "", today, used / divisor, now))
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
	now = frappe.utils.now_datetime()
	for check in checks:
		# A day with no row is readiness M1's to flag; here it is only compared when it exists.
		stored = peaks.get((check.subject, ""))
		mismatch = stored is not None and stored < check.read_value * (1 - STORAGE_TOLERANCE)
		frappe.db.set_value(
			DOCTYPE,
			check.name,
			{"stored_value": stored or 0, "checked_at": now, "is_mismatch": mismatch},
			update_modified=False,
		)
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
	client = GroveClient.from_settings()
	meter = frappe.get_doc("Service", AI_SERVICE).get_meter(AI_METER)
	stored = _stored(AI_SERVICE, day, list(subjects))
	now = frappe.utils.now_datetime()
	rows, failed = [], []
	for team, team_service in subjects.items():
		# One team's failure, of any kind, must not stop the page's other teams.
		try:
			read = {
				row["dimension"]: row["quantity"] for row in landing_rows(client, team_service, meter, day)
			}
		except Exception as error:
			failed.append(f"{team}: {error!r}")
			continue
		rows += _ai_checks(team, day, read, stored, now)
	_log_failures(f"Usage check: {len(failed)} AI team(s) not read", failed)
	return _insert(rows)


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
	return [
		{
			"alert": "silent_service",
			"doctype": "Service",
			"subject": service.name,
			"team": None,
			"detail": _silence_detail(service),
		}
		for service in services
		if _is_silent(service, now)
	]


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


def is_read_by_central(service: str) -> bool:
	return bool(frappe.db.get_value("Service", service, "central_reads"))


def _is_silent(service, now: datetime.datetime) -> bool:
	window = datetime.timedelta(hours=2 * CADENCE_HOURS.get(service.expected_cadence, 1))
	return not service.last_report_at or service.last_report_at < now - window


def _silence_detail(service) -> str:
	if not service.last_report_at:
		return f"No report since Central stopped reading it (expected {service.expected_cadence or 'Hourly'})"
	return (
		f"Last report {service.last_report_at} ({frappe.utils.get_system_timezone()}) "
		f"(expected {service.expected_cadence or 'Hourly'})"
	)


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


def _ai_checks(team: str, day: str, read: dict, stored: dict, now) -> list[dict]:
	"""One check per model Grove or the ledger has for the team that day."""
	models = set(read) | {model for subject, model in stored if subject == team}
	rows = []
	for model in sorted(models):
		grove, kept = read.get(model, 0.0), stored.get((team, model), 0.0)
		row = _check(AI_SERVICE, AI_METER, team, model, day, grove, now)
		row.update(stored_value=kept, checked_at=now, is_mismatch=abs(grove - kept) > AI_TOLERANCE_USD)
		rows.append(row)
	return rows


def _stored(service: str, day, subjects: list[str]) -> dict:
	"""The stored quantity of each subject and dimension on a day."""
	if not subjects:
		return {}
	rows = frappe.get_all(
		"Usage Day",
		filters={"service": service, "day": day, "subject": ["in", subjects]},
		fields=["subject", "dimension", "quantity"],
	)
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


def _used_bytes(client, name: str) -> float:
	try:
		return frappe.utils.flt(client.get_usage(name)["usage"].get("used_bytes"))
	except ObjectStorageNotFound:
		# A server's backup bucket that was never attached holds nothing.
		return 0.0


def _divisor(service: str, meter: str) -> float:
	return frappe.utils.flt(frappe.get_doc("Service", service).get_meter(meter).unit_divisor)


def _enqueue(method: str, **kwargs) -> None:
	from central.billing.revenue.invoicing.run import billing_queue

	frappe.enqueue(f"central.billing.revenue.usage_checks.{method}", queue=billing_queue(), **kwargs)


def _log_failures(title: str, failed: list[str]) -> None:
	if failed:
		frappe.log_error(title=title, message="\n".join(failed[:LOGGED_FAILURES]))
