# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import datetime

import frappe
from frappe.query_builder import Criterion

DOCTYPE = "Usage Day"
LEVEL = "Level"
KEPT_MONTHS = 13
# A UTC day is estimated only after the day has ended and late lines have had 48 hours.
ESTIMATE_AFTER_DAYS = 3
ESTIMATE_LOOKBACK_DAYS = 7
DELETE_PAGE = 5000

_INSERT_FIELDS = (
	"name",
	"creation",
	"modified",
	"owner",
	"modified_by",
	"service",
	"meter",
	"subject",
	"day",
	"aggregation",
	"team",
	"subscription",
	"resource_type",
	"quantity",
	"unit",
	"source_amount",
	"source_currency",
	"as_of",
	"landed_at",
	"estimated",
)


def write_days(rows: list[dict]) -> int:
	"""Store each line as its subject's row for that UTC day, and return how many rows changed.

	A new day is inserted. An existing day takes the line only when it is a real reading over an
	estimate, a higher Level peak, or a newer Sum total. A billed day is never changed.
	"""
	rows = _merged(rows)
	if not rows:
		return 0
	existing = _existing_days(rows)
	now = frappe.utils.now_datetime()
	fresh, changed = [], []
	for row in rows:
		current = existing.get(_key(row))
		if current is None:
			fresh.append(row)
		elif is_newer(current, row):
			changed.append((current.name, row))
	_insert(fresh, now)
	for name, row in changed:
		_update(name, row, now)
	return len(fresh) + len(changed)


def is_newer(current, row: dict) -> bool:
	"""Whether `row` should replace the stored day `current`."""
	if current.get("invoice") or row.get("estimated"):
		return False
	if current.get("estimated"):
		return True
	if current.get("aggregation") == LEVEL:
		return frappe.utils.flt(row["quantity"]) > frappe.utils.flt(current.get("quantity"))
	return frappe.utils.get_datetime(row["as_of"]) > frappe.utils.get_datetime(current.get("as_of"))


def _merged(rows: list[dict]) -> list[dict]:
	"""One line per subject, meter and day: a batch may carry the same day twice."""
	kept: dict = {}
	for row in rows:
		# Float columns are NOT NULL in Frappe, so a blank amount is stored as 0.
		row = {
			**row,
			"quantity": frappe.utils.flt(row.get("quantity")),
			"source_amount": frappe.utils.flt(row.get("source_amount")),
		}
		key = _key(row)
		if key not in kept or is_newer(kept[key], row):
			kept[key] = row
	return list(kept.values())


def stamp_invoice(team: str, period_end, invoice: str) -> None:
	"""Mark every unbilled day up to the period end, and every unbilled rollup in it, as billed."""
	day = frappe.qb.DocType(DOCTYPE)
	(
		frappe.qb.update(day)
		.set(day.invoice, invoice)
		.where((day.team == team) & day.invoice.isnull() & (day.day <= period_end))
	).run()
	rollup = frappe.qb.DocType("Usage Rollup")
	(
		frappe.qb.update(rollup)
		.set(rollup.invoice, invoice)
		.where(
			(rollup.team == team)
			& rollup.invoice.isnull()
			& rollup.superseded_by.isnull()
			& (rollup.period_start <= period_end)
		)
	).run()


def release_invoice(invoice: str) -> None:
	"""Unmark what a cancelled invoice billed, so the invoice that replaces it bills it again."""
	for doctype in (DOCTYPE, "Usage Rollup"):
		table = frappe.qb.DocType(doctype)
		frappe.qb.update(table).set(table.invoice, None).where(table.invoice == invoice).run()


def fill_missing_days(today=None) -> int:
	"""Daily: give a Level subject that went silent its last reading, marked estimated (D-27)."""
	last = _utc_date(today) - datetime.timedelta(days=ESTIMATE_AFTER_DAYS)
	written = 0
	for offset in range(ESTIMATE_LOOKBACK_DAYS, -1, -1):
		written += _estimate_day(last - datetime.timedelta(days=offset))
	return written


def prune_old_days(today=None) -> int:
	"""Daily: delete billed days older than the kept months. The monthly rollup keeps their total."""
	cutoff = frappe.utils.add_months(_utc_date(today).replace(day=1), -KEPT_MONTHS)
	deleted = 0
	while names := frappe.get_all(
		DOCTYPE,
		filters={"day": ["<", cutoff], "invoice": ["is", "set"]},
		pluck="name",
		limit=DELETE_PAGE,
	):
		table = frappe.qb.DocType(DOCTYPE)
		frappe.qb.from_(table).delete().where(table.name.isin(names)).run()
		deleted += len(names)
	return deleted


def utc_today() -> datetime.date:
	return datetime.datetime.now(datetime.UTC).date()


def _utc_date(today) -> datetime.date:
	return frappe.utils.getdate(today) if today else utc_today()


def _estimate_day(day: datetime.date) -> int:
	"""Copy the previous day's Level rows onto `day` for live subjects that have no row on it."""
	previous = frappe.get_all(
		DOCTYPE,
		filters={"day": day - datetime.timedelta(days=1), "aggregation": LEVEL},
		fields=list(_INSERT_FIELDS[5:]),
	)
	if not previous:
		return 0
	live = _live_subjects({row.service for row in previous})
	rows = [
		{**row, "day": day, "estimated": 1, "as_of": None, "landed_at": None}
		for row in previous
		if (row.service, row.subject) in live
	]
	return write_days(rows)


def _live_subjects(services: set) -> set:
	"""(service, subject) of every service a team still has, suspended ones included."""
	return {
		(row.add_on_service, row.external_id)
		for row in frappe.get_all(
			"Team Service",
			filters={"add_on_service": ["in", list(services)], "subscription": ["is", "set"]},
			fields=["add_on_service", "external_id"],
		)
	}


def _key(row) -> tuple:
	return (row["service"], row["subject"], row["meter"], str(frappe.utils.getdate(row["day"])))


def _existing_days(rows: list[dict]) -> dict:
	"""The stored days for these lines, by key. One query for the whole batch."""
	day = frappe.qb.DocType(DOCTYPE)
	found = (
		frappe.qb.from_(day)
		.select(day.name, day.service, day.subject, day.meter, day.day, day.aggregation)
		.select(day.quantity, day.as_of, day.estimated, day.invoice)
		.where(
			Criterion.all(
				[
					day.service.isin(list({row["service"] for row in rows})),
					day.subject.isin(list({row["subject"] for row in rows})),
					day.day.isin(list({frappe.utils.getdate(row["day"]) for row in rows})),
				]
			)
		)
	).run(as_dict=True)
	return {_key(row): row for row in found}


def _insert(rows: list[dict], now) -> None:
	if not rows:
		return
	user = frappe.session.user
	values = [
		(
			frappe.generate_hash(length=12),
			now,
			now,
			user,
			user,
			*(row.get(field) for field in _INSERT_FIELDS[5:-2]),
			now,
			frappe.utils.cint(row.get("estimated")),
		)
		for row in rows
	]
	# A day another worker inserted a moment ago is skipped here; its next report updates it.
	frappe.db.bulk_insert(DOCTYPE, list(_INSERT_FIELDS), values, ignore_duplicates=True)


def _update(name: str, row: dict, now) -> None:
	day = frappe.qb.DocType(DOCTYPE)
	(
		frappe.qb.update(day)
		.set(day.quantity, row["quantity"])
		.set(day.source_amount, row.get("source_amount"))
		.set(day.as_of, row.get("as_of"))
		.set(day.estimated, 0)
		.set(day.landed_at, now)
		.set(day.modified, now)
		.where((day.name == name) & day.invoice.isnull())
	).run()
