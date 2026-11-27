# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import datetime

import frappe
from frappe import _

from central.billing.revenue import usage_month, usage_reports
from central.billing.revenue.usage_month import DOCTYPE, LEVEL, Written, is_newer, month_of

# A UTC day is estimated only after the day has ended and late lines have had 48 hours.
ESTIMATE_AFTER_DAYS = 3
ESTIMATE_LOOKBACK_DAYS = 7
READ_PAGE = 1000
# What a line copied as an estimate carries from the reading it copies.
_LINE_FIELDS = (
	"service",
	"meter",
	"subject",
	"dimension",
	"day",
	"aggregation",
	"team",
	"subscription",
	"resource_type",
	"quantity",
	"included",
	"unit",
	"source_amount",
	"source_currency",
	"as_of",
	"written_off",
)


def write_days(rows: list[dict], report: str | None, source: str) -> Written:
	"""Store each line in its subject's month row, on the slot of its UTC day, naming its report."""
	# An unbilled day takes a line only when it is a real reading over an estimate, a higher Level
	# peak, a Level day's new bundle or a newer Sum total. A billed day is kept as a correction.
	return usage_month.write_lines(_merged(rows), report, source)


class CentralLines:
	"""Lines Central reads or estimates itself, kept as one report per service."""

	def __init__(self, kind: str):
		self.kind = kind
		self.names: dict[str, str] = {}
		self.lines: dict[str, list[dict]] = {}
		self.written: dict[str, int] = {}

	def write(self, rows: list[dict]) -> Written:
		"""Write the lines of each service under that service's report. Any line not stored fails the job."""
		total = Written()
		by_service: dict[str, list[dict]] = {}
		for row in rows:
			by_service.setdefault(row["service"], []).append(row)
		for service, lines in by_service.items():
			# The report is kept after its lines, so it is kept only when a line set a value.
			name = self.names.setdefault(service, frappe.generate_hash(length=10))
			written = write_days(lines, name, self.kind)
			if written.conflicts:
				# A refused lock rolls back the whole transaction, with every batch written before
				# it, so the job fails and reads again rather than keep a report of lines not stored.
				raise frappe.QueryDeadlockError(_("Usage days changed while they were written."))
			self.lines.setdefault(service, []).extend(lines)
			self.written[service] = self.written.get(service, 0) + written.count + written.corrections
			total.count += written.count
			total.corrections += written.corrections
		return total

	def keep(self) -> None:
		"""Keep a report for each service whose lines set a value."""
		for service, lines in self.lines.items():
			if not self.written.get(service):
				continue
			name = usage_reports.record_lines(service, self.kind, lines, name=self.names[service])
			usage_reports.set_counts(name, self.written[service], 0)


def write_central_days(rows: list[dict], kind: str = usage_reports.READ_BY_CENTRAL) -> Written:
	"""Write lines Central read itself and keep them as its own report."""
	lines = CentralLines(kind)
	written = lines.write(rows)
	lines.keep()
	return written


def _merged(rows: list[dict]) -> list[dict]:
	"""One line per subject, meter, dimension and day: a batch may carry the same day twice."""
	kept: dict = {}
	bill_from = _bill_from({row["service"] for row in rows})
	for row in rows:
		# Float columns are NOT NULL in Frappe, so a blank amount is stored as 0. A blank dimension is
		# stored as "", not NULL, so the unique key still holds.
		row = {
			**row,
			"dimension": row.get("dimension") or "",
			"quantity": frappe.utils.flt(row.get("quantity")),
			"source_amount": frappe.utils.flt(row.get("source_amount")),
			"written_off": _is_before_billing(row, bill_from.get(row["service"])),
		}
		if "included" in row:
			# Only a line that carries a bundle may change a stored day's one; absent is not 0.
			row["included"] = frappe.utils.flt(row["included"])
		key = _key(row)
		if key not in kept or is_newer(kept[key], row):
			kept[key] = row
	return list(kept.values())


def fill_missing_days(today=None) -> int:
	"""Daily: give a Level subject that went silent its last reading, marked estimated."""
	last = _utc_date(today) - datetime.timedelta(days=ESTIMATE_AFTER_DAYS)
	estimates = CentralLines(usage_reports.ESTIMATED)
	written = 0
	for offset in range(ESTIMATE_LOOKBACK_DAYS, -1, -1):
		written += _estimate_day(last - datetime.timedelta(days=offset), estimates)
	estimates.keep()
	return written


def utc_today() -> datetime.date:
	return datetime.datetime.now(datetime.UTC).date()


def _utc_date(today) -> datetime.date:
	return frappe.utils.getdate(today) if today else utc_today()


def utc_day_start(day) -> datetime.datetime:
	"""The moment a UTC day begins, in system time."""
	start = datetime.datetime.combine(frappe.utils.getdate(day), datetime.time(), datetime.UTC)
	return frappe.utils.convert_utc_to_system_timezone(start).replace(tzinfo=None)


def utc_day_window(day) -> tuple[datetime.datetime, datetime.datetime]:
	"""The start and end of a UTC day, in system time."""
	day = frappe.utils.getdate(day)
	return utc_day_start(day), utc_day_start(day + datetime.timedelta(days=1))


def _estimate_day(day: datetime.date, estimates: CentralLines) -> int:
	"""Copy each Level subject's last recent reading onto `day` when the subject is billed on it."""
	# Not only yesterday's: a server paused until `day` has its last reading before the pause.
	previous = _last_readings(day)
	if not previous:
		return 0
	live = _live_subjects({row.service for row in previous}, day)
	rows = [
		_estimated(row, day, live[(row.service, row.subject)])
		for row in previous
		if (row.service, row.subject) in live
	]
	return estimates.write(rows).count


def _last_readings(day: datetime.date) -> list:
	"""The latest Level day of each subject, meter and dimension in the lookback days before `day`."""
	first = day - datetime.timedelta(days=ESTIMATE_LOOKBACK_DAYS)
	last = day - datetime.timedelta(days=1)
	latest: dict = {}
	for row in _level_days({month_of(first), month_of(last)}):
		if not first <= row.day <= last:
			continue
		key = (row.service, row.subject, row.meter, row.dimension)
		if key not in latest or latest[key].day < row.day:
			latest[key] = row
	return list(latest.values())


def _level_days(months: set) -> list:
	"""Every filled day of the Level month rows of `months`, read a page at a time."""
	days, start = [], 0
	while page := frappe.get_all(
		DOCTYPE,
		filters={"month": ["in", list(months)], "aggregation": LEVEL, "filled": ["!=", 0]},
		pluck="name",
		order_by="name asc",
		limit_start=start,
		limit_page_length=READ_PAGE,
	):
		days += usage_month.day_rows({"name": ["in", page]})
		start += READ_PAGE
	return days


def _estimated(row, day: datetime.date, subject) -> dict:
	"""A subject's last reading as `day`'s estimate, naming the day it copied."""
	# A server resized since its last reading has that day's bundle, not the reading's.
	line = {name: row.get(name) for name in _LINE_FIELDS}
	included = subject.get("included", row.included)
	return {**line, "day": day, "included": included, "estimated": 1, "as_of": None, "copied_day": row.day}


def _live_subjects(services: set, day: datetime.date) -> dict:
	"""Each (service, subject) a team still has on `day`, suspended ones included."""
	from central.billing.revenue.bundled_buckets import billed_subjects_of

	return {
		(service, name): subject
		for service in services
		for name, subject in billed_subjects_of(service, day).items()
	}


def _key(row) -> tuple:
	day = str(frappe.utils.getdate(row["day"]))
	return (row["service"], row["subject"], row["meter"], row.get("dimension") or "", day)


def _bill_from(services: set) -> dict:
	"""The first billed day of each service that starts billing later than its usage."""
	rows = frappe.get_all(
		"Service",
		filters={"name": ["in", list(services)], "bill_from": ["is", "set"]},
		fields=["name", "bill_from"],
	)
	return {row.name: row.bill_from for row in rows}


def _is_before_billing(row: dict, bill_from) -> int:
	return int(bool(bill_from) and frappe.utils.getdate(row["day"]) < frappe.utils.getdate(bill_from))
