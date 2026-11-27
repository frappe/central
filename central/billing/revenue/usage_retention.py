# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import datetime

import frappe

from central.billing.platform.invariants import Violation
from central.billing.platform.jobs import each_isolated
from central.billing.revenue import usage_reports
from central.billing.revenue.usage_month import DAY_FIELDS, OPEN
from central.billing.revenue.usage_month_rows import CORRECTION, DOCTYPE

# Usage evidence is kept this long; a dispute window must end well before it.
RETENTION_MONTHS = 13
PAGE_SIZE = 500
# The daily integrity check re-hashes this many recent report bodies.
SAMPLE_SIZE = 20
SAMPLE_DAYS = 35


def prune_old_months(today=None) -> int:
	"""Daily: clear the day values and slots of month rows past retention, keeping their totals and terms."""
	cutoff = retention_cutoff(today)
	pruned, after = 0, ""
	while page := _prunable_months(cutoff, after):
		pruned += len(each_isolated("Usage month prune", DOCTYPE, page, _prune_month))
		after = page[-1]
	return pruned


def prune_reports(today=None) -> int:
	"""Daily: delete the Usage Reports past retention, with their bodies."""
	cutoff = retention_cutoff(today)
	deleted, after = 0, ""
	while page := _old_reports(cutoff, after):
		deleted += len(each_isolated("Usage report prune", usage_reports.DOCTYPE, page, _delete_report))
		after = page[-1]
	return deleted


def sample_report_bodies(today=None) -> int:
	"""Daily: re-hash a small random sample of recent report bodies and mark each that no longer matches."""
	since = frappe.utils.add_days(frappe.utils.getdate(today), -SAMPLE_DAYS)
	damaged = [name for name in _sample(since) if not _is_body_intact(name)]
	now = frappe.utils.now_datetime()
	for name in damaged:
		frappe.db.set_value(usage_reports.DOCTYPE, name, "damaged_at", now, update_modified=False)
	return len(damaged)


def retention_cutoff(today=None) -> datetime.date:
	"""The first day of the oldest month still kept in full."""
	return frappe.utils.add_months(frappe.utils.getdate(today).replace(day=1), -RETENTION_MONTHS)


def check_billed_days_name_a_report() -> list[Violation]:
	"""Every day billed in the last two months names a Usage Report, and every recent report keeps its body.

	A billed day with no report cannot be shown to a customer who disputes it."""
	since = frappe.utils.add_months(frappe.utils.getdate().replace(day=1), -1)
	return _unreported_months(since) + _reports_without_body(since)


def check_report_bodies_are_intact() -> list[Violation]:
	"""Every report body the daily sample re-hashed still has the hash recorded when it was received."""
	damaged = frappe.get_all(
		usage_reports.DOCTYPE,
		filters={"damaged_at": ["is", "set"]},
		fields=["name", "service", "received_at", "damaged_at"],
		order_by="damaged_at desc",
		limit=50,
	)
	return [
		Violation(
			check="M6",
			subject_doctype=usage_reports.DOCTYPE,
			subject=report.name,
			detail=f"The {report.service} report received {report.received_at} no longer matches its hash (found {report.damaged_at}). Restore the file from a backup.",
		)
		for report in damaged
	]


def _prunable_months(cutoff: datetime.date, after: str) -> list[str]:
	"""Month rows past retention with nothing left to bill, by name."""
	month = frappe.qb.DocType(DOCTYPE)
	correction = frappe.qb.DocType(CORRECTION)
	open_corrections = frappe.qb.from_(correction).select(correction.parent).where(correction.status == OPEN)
	return (
		frappe.qb.from_(month)
		.select(month.name)
		.where(
			(month.month < cutoff)
			& (month.open_days == 0)
			& (month.pruned == 0)
			& (month.name > after)
			& month.name.notin(open_corrections)
		)
		.orderby(month.name)
		.limit(PAGE_SIZE)
	).run(pluck=True)


def _prune_month(name: str) -> None:
	month = frappe.qb.DocType(DOCTYPE)
	query = frappe.qb.update(month).set(month.slots, None).set(month.pruned, 1)
	for day_field in DAY_FIELDS:
		query = query.set(month[day_field], 0)
	# A day that became open since the page was read keeps its value.
	query.where((month.name == name) & (month.open_days == 0)).run()


def _old_reports(cutoff: datetime.date, after: str) -> list[str]:
	return frappe.get_all(
		usage_reports.DOCTYPE,
		filters={"received_at": ["<", cutoff], "name": [">", after]},
		order_by="name asc",
		limit=PAGE_SIZE,
		pluck="name",
	)


def _delete_report(name: str) -> None:
	files = frappe.get_all(
		"File",
		filters={"attached_to_doctype": usage_reports.DOCTYPE, "attached_to_name": name},
		pluck="name",
	)
	for file in files:
		# Evidence past retention belongs to no user; deleting the File also removes its bytes.
		frappe.delete_doc("File", file, ignore_permissions=True, force=True)
	# Pruned month rows and old corrections still name the report, so the link check would refuse.
	frappe.db.delete(usage_reports.DOCTYPE, {"name": name})


def _sample(since) -> list[str]:
	"""Recent reports from a random point in name order, so each run checks different ones."""
	start = frappe.generate_hash(length=10)
	window = {"received_at": [">=", since], "damaged_at": ["is", "not set"]}
	found = frappe.get_all(
		usage_reports.DOCTYPE,
		filters={**window, "name": [">=", start]},
		order_by="name asc",
		limit=SAMPLE_SIZE,
		pluck="name",
	)
	if len(found) < SAMPLE_SIZE:
		found += frappe.get_all(
			usage_reports.DOCTYPE,
			filters={**window, "name": ["<", start]},
			order_by="name asc",
			limit=SAMPLE_SIZE - len(found),
			pluck="name",
		)
	return found


def _is_body_intact(name: str) -> bool:
	try:
		return usage_reports.is_intact(name)
	except (OSError, EOFError):
		# A missing file or a broken gzip stream is a damaged body.
		return False


def _unreported_months(since) -> list[Violation]:
	month = frappe.qb.DocType(DOCTYPE)
	rows = (
		frappe.qb.from_(month)
		.select(month.name, month.team, month.subject, month.month, month.unreported)
		.where((month.unreported > 0) & (month.month >= since) & (month.pruned == 0))
		.limit(200)
	).run(as_dict=True)
	return [
		Violation(
			check="M5",
			team=row.team,
			subject_doctype=DOCTYPE,
			subject=row.name,
			detail=f"{row.subject} ({row.month:%B %Y}): {row.unreported.bit_count()} billed day(s) name no Usage Report.",
			actual=row.unreported.bit_count(),
		)
		for row in rows
	]


def _reports_without_body(since) -> list[Violation]:
	reports = frappe.get_all(
		usage_reports.DOCTYPE,
		filters={"received_at": [">=", since], "body": ["is", "not set"]},
		fields=["name", "service", "received_at"],
		limit=200,
	)
	return [
		Violation(
			check="M5",
			subject_doctype=usage_reports.DOCTYPE,
			subject=report.name,
			detail=f"The {report.service} report received {report.received_at} keeps no body. Restore the file from a backup.",
		)
		for report in reports
	]
