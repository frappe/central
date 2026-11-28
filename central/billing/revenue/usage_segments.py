# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""State meters kept as Usage Segments, and the day slots of Usage Month projected from them.

A subject doctype plugs in through the `billing_segment_subjects` hook, which names a module with
billed_windows(subjects, before) and team_subjects(team). Its writer calls set_quantity.
"""

import datetime

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import Order

from central.billing.doctype.usage_segment.usage_segment import get_last_segment
from central.billing.platform.jobs import each_isolated
from central.billing.platform.records import save_billing_record
from central.billing.revenue import usage_month
from central.billing.revenue.usage_ledger import utc_day_start, utc_day_window, utc_today
from central.billing.revenue.usage_month import STATE
from central.billing.revenue.usage_month_days import subjects_with_day
from central.billing.revenue.usage_month_rows import DOCTYPE as MONTH_DOCTYPE
from central.billing.revenue.usage_month_rows import month_of

DOCTYPE = "Usage Segment"
STATE_REPORT = "State Report"
TERMINATION = "Termination"
OPERATOR = "Operator"
MIGRATION = "Migration"
# The source a projected day slot names; the slot also names the segment it came from.
SEGMENT = "Segment"
PAGE_SIZE = 500
SUBJECTS_HOOK = "billing_segment_subjects"
# Subject doctypes already logged as having no provider, so each is logged once per process.
_unregistered: set[str] = set()


def set_quantity(
	service: str, meter: str, subject: Document, quantity: float, at, source: str, reference=None
):
	"""Record that `subject` holds `quantity` of a state meter from `at`, closing the segment it replaces."""
	if not is_state_meter(service, meter):
		# Until the migration the meter keeps day values, and a segment beside them would bill twice.
		return
	# The subject's own save holds its row lock, so this read and the write after it run one at a time.
	last = get_last_segment(service, meter, subject.name, for_update=True)
	current = last if last and not last.ends_at else None
	if _quantity_of(current) == frappe.utils.flt(quantity):
		return
	at = _not_before(at, last)
	if current:
		close_segment(current.name, at, source, reference)
	if quantity > 0:
		insert_segment(
			service=service,
			meter=meter,
			subject=subject.name,
			subject_doctype=subject.doctype,
			team=subject.team,
			quantity=quantity,
			starts_at=at,
			opened_source=source,
			opened_reference=reference,
		)


def insert_segment(**values) -> Document:
	"""Insert one segment, opened by the current user."""
	segment = frappe.get_doc({"doctype": DOCTYPE, "opened_by": frappe.session.user, **values})
	# The save that carries the change was already permitted, and a segment has no permission of its own.
	return segment.insert(ignore_permissions=True)


def close_segment(name: str, at, source: str, reference=None) -> None:
	"""Close an open segment at `at`."""
	segment = frappe.get_doc(DOCTYPE, name)
	segment.update(
		{
			"ends_at": at,
			"closed_by": frappe.session.user,
			"closed_source": source,
			"closed_reference": reference,
		}
	)
	save_billing_record(segment)


def is_state_meter(service: str, meter: str) -> bool:
	"""Whether the meter keeps its usage as segments."""
	return (
		frappe.db.get_value("Service Meter", {"parent": service, "meter_key": meter}, "aggregation") == STATE
	)


def open_subjects(service: str, meter: str) -> list[str]:
	"""The subjects that hold some of a state meter now."""
	return frappe.get_all(
		DOCTYPE,
		filters={"service": service, "meter": meter, "ends_at": ["is", "not set"]},
		pluck="subject",
	)


def _quantity_of(segment) -> float:
	return frappe.utils.flt(segment.quantity) if segment else 0.0


def _not_before(at, last) -> datetime.datetime:
	"""`at`, moved up to the start or end of the subject's last segment, so segments never overlap."""
	at = frappe.utils.get_datetime(at)
	if not last:
		return at
	return max(at, frappe.utils.get_datetime(last.ends_at or last.starts_at))


def project_team(team: str, period_end) -> int:
	"""Write the state days of a team's subjects for the month a draft bills and the month before."""
	until = frappe.utils.getdate(period_end)
	# A day of the month before can land after that month closed, and still bills in this draft.
	since = frappe.utils.add_months(month_of(until), -1)
	# A subject moved to the team keeps its segments under the old team, so its subscriptions count too.
	subjects = sorted(set(_team_subjects(team, since, until)) | set(_billed_subjects(team)))
	return project(subjects, since, until) if subjects else 0


def project_changed(since) -> int:
	"""Hourly: write the days of segments opened or closed since `since`, and today for each held state."""
	today = utc_today()
	# A changed segment may reach back into the month before, which a draft may not have closed yet.
	written = _project_pages(_changed_subjects(since), frappe.utils.add_months(month_of(today), -1), today)
	# Yesterday too, so an hour the scheduler missed after midnight still writes its day.
	return written + _project_pages(_subjects_without_day(today), today - datetime.timedelta(days=1), today)


def project(subjects: list[str], since, until) -> int:
	"""Write each UTC day from `since` to `until` that a subject held a state at a moment it was billed."""
	segments = _segments_of(subjects, since, until)
	lines = []
	for (service, meter), rows in segments.items():
		lines += _day_lines(service, meter, rows, since, until)
	written = usage_month.write_lines(lines, report=None, source=SEGMENT)
	if written.conflicts:
		# The whole batch rolls back, so the job fails and writes it again on its next run.
		raise frappe.QueryDeadlockError(_("Usage days changed while they were written."))
	return written.count + written.corrections


def _held_days(segments: list, windows: dict[str, list], days: list[tuple], cap) -> dict[tuple, frappe._dict]:
	"""The most each subject held at once on each day while it was billed, before `cap`, by (subject, day)."""
	found: dict[tuple, frappe._dict] = {}
	for segment in segments:
		for window in windows.get(segment.subject, []):
			start = max(segment.starts_at, window.start)
			end = min(segment.ends_at or cap, window.end or cap, cap)
			# Held and billed at the same moment, not only on the same day.
			if start < end:
				_add_days(found, segment, window, (start, end), days)
	return found


def _project_pages(subjects: list[tuple[str, str]], since, until) -> int:
	"""Project the subjects of each doctype one page at a time, so a failed page never stops the rest."""
	by_doctype: dict[str, set] = {}
	for doctype, subject in subjects:
		by_doctype.setdefault(doctype, set()).add(subject)
	return sum(
		_project_doctype(doctype, sorted(names), since, until) for doctype, names in by_doctype.items()
	)


def _project_doctype(doctype: str, names: list[str], since, until) -> int:
	pages = {names[start]: names[start : start + PAGE_SIZE] for start in range(0, len(names), PAGE_SIZE)}
	counts = each_isolated(
		"Usage segment days",
		doctype,
		list(pages),
		lambda first: project(pages[first], since, until),
	)
	return sum(counts)


def _utc_days(since, until) -> list[tuple]:
	"""Each UTC day from `since` to `until`, with its start and end in system time."""
	since, until = frappe.utils.getdate(since), frappe.utils.getdate(until)
	count = (until - since).days + 1
	return [(day, *utc_day_window(day)) for day in (since + datetime.timedelta(days=n) for n in range(count))]


def _day_lines(service: str, meter_key: str, segments: list, since, until) -> list[dict]:
	"""One line per subject and UTC day it held the state while billed, from the service's first billed day."""
	bill_from = frappe.db.get_value("Service", service, "bill_from")
	if not bill_from:
		# Before the cutover the per-address subscriptions still bill.
		return []
	since = max(frappe.utils.getdate(since), frappe.utils.getdate(bill_from))
	before = utc_day_start(frappe.utils.getdate(until) + datetime.timedelta(days=1))
	now = frappe.utils.now_datetime()
	# A draft written before its period ends must not count the days still to come.
	held = _held_days(segments, _billed_windows(segments, before), _utc_days(since, until), min(before, now))
	_keep_written_subscriptions(held, service, meter_key, since, until)
	meter = frappe.get_doc("Service", service).get_meter(meter_key)
	return [
		meter.get_day_row(found, day, found.quantity, dimension="", as_of=now, segment=found.segment)
		for (_, day), found in held.items()
	]


def _keep_written_subscriptions(held: dict, service: str, meter: str, since, until) -> None:
	"""Keep each day on the subscription whose month row already holds it."""
	subjects = list({key[0] for key in held})
	# A team edit can bill two subscriptions of one subject on one day, and the day bills only once.
	for key, written in _written_days(service, meter, subjects, since, until).items():
		if key in held:
			held[key].update(written)


def _written_days(service: str, meter: str, subjects: list[str], since, until) -> dict[tuple, frappe._dict]:
	"""The subscription and team of the month row that holds each subject's day, by (subject, day)."""
	if not subjects:
		return {}
	rows = frappe.get_all(
		MONTH_DOCTYPE,
		filters={
			"service": service,
			"meter": meter,
			"subject": ["in", subjects],
			"month": ["between", [month_of(since), month_of(until)]],
		},
		fields=["subject", "month", "subscription", "team", "filled"],
	)
	return {
		(row.subject, row.month.replace(day=day)): frappe._dict(subscription=row.subscription, team=row.team)
		for row in rows
		for day in usage_month.days_of(row.filled)
	}


def _add_days(found: dict, segment, window, held: tuple, days: list[tuple]) -> None:
	"""Keep, for each day the held stretch touches, the most held and the subscription billed then."""
	start, end = held
	for day, day_start, day_end in days:
		key = (segment.subject, day)
		if max(start, day_start) < min(end, day_end) and _is_more(found.get(key), segment, window):
			found[key] = frappe._dict(
				external_id=segment.subject,
				team=window.team,
				subscription=window.subscription,
				quantity=frappe.utils.flt(segment.quantity),
				segment=segment.name,
				billed_from=window.start,
			)


def _is_more(kept, segment, window) -> bool:
	"""Whether the segment beats the day's kept value: more held, or as much on an earlier subscription."""
	if not kept:
		return True
	quantity = frappe.utils.flt(segment.quantity)
	return quantity > kept.quantity or (quantity == kept.quantity and window.start < kept.billed_from)


def _segments_of(subjects: list[str], since, until) -> dict[tuple, list]:
	"""The segments of the subjects held at some moment from `since` to `until`, by service and meter."""
	if not subjects:
		return {}
	table = frappe.qb.DocType(DOCTYPE)
	rows = (
		frappe.qb.from_(table)
		.select(table.name, table.service, table.meter, table.subject_doctype, table.subject, table.quantity)
		.select(table.starts_at, table.ends_at)
		.where(table.subject.isin(subjects))
		.where(table.starts_at < utc_day_window(until)[1])
		.where(table.ends_at.isnull() | (table.ends_at > utc_day_start(since)))
		.orderby(table.starts_at, order=Order.asc)
	).run(as_dict=True)
	by_meter: dict[tuple, list] = {}
	for row in rows:
		by_meter.setdefault((row.service, row.meter), []).append(row)
	return by_meter


def _team_subjects(team: str, since, until) -> list[str]:
	"""The subjects of a team's segments held at some moment from `since` to `until`."""
	table = frappe.qb.DocType(DOCTYPE)
	return (
		frappe.qb.from_(table)
		.select(table.subject)
		.distinct()
		.where(table.team == team)
		.where(table.starts_at < utc_day_window(until)[1])
		.where(table.ends_at.isnull() | (table.ends_at > utc_day_start(since)))
	).run(pluck=True)


def _billed_windows(segments: list, before) -> dict[str, list]:
	"""The billed windows of the segments' subjects before `before`, from each subject doctype's provider."""
	by_doctype: dict[str, set] = {}
	for segment in segments:
		by_doctype.setdefault(segment.subject_doctype, set()).add(segment.subject)
	windows: dict[str, list] = {}
	for doctype, subjects in by_doctype.items():
		if provider := _provider(doctype):
			windows.update(provider.billed_windows(sorted(subjects), before))
	return windows


def _billed_subjects(team: str) -> list[str]:
	"""The subjects of every registered doctype that the team's subscriptions bill."""
	return [subject for doctype in _providers() for subject in _provider(doctype).team_subjects(team)]


def _providers() -> dict[str, list[str]]:
	return frappe.get_hooks(SUBJECTS_HOOK) or {}


def _provider(doctype: str):
	"""The module that knows when a doctype's subjects were billed, else None."""
	paths = _providers().get(doctype)
	if paths:
		return frappe.get_module(paths[-1])
	if doctype not in _unregistered:
		# A segment of an unknown doctype bills nothing, and the rest of the recount still runs.
		_unregistered.add(doctype)
		frappe.logger("billing").warning(
			f"No {SUBJECTS_HOOK} provider for {doctype}; its segments bill nothing."
		)
	return None


def _changed_subjects(since) -> list[tuple[str, str]]:
	"""The subjects, with their doctype, of the segments opened or closed since `since`."""
	return frappe.get_all(
		DOCTYPE,
		filters={"modified": [">", since]},
		fields=["subject_doctype", "subject"],
		distinct=True,
		as_list=True,
	)


def _subjects_without_day(today) -> list[tuple[str, str]]:
	"""The subjects, with their doctype, that hold a state now and have no value for today yet."""
	rows = frappe.get_all(
		DOCTYPE, filters={"ends_at": ["is", "not set"]}, fields=["service", "subject_doctype", "subject"]
	)
	by_service: dict[str, set] = {}
	for row in rows:
		by_service.setdefault(row.service, set()).add((row.subject_doctype, row.subject))
	missing = []
	for service, subjects in by_service.items():
		with_day = subjects_with_day(service, today)
		missing += [(doctype, subject) for doctype, subject in subjects if subject not in with_day]
	return missing
