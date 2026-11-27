# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""State meters, such as the public IPv4 addresses of a server, kept as Usage Segments."""

import datetime

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import Order

from central.billing.catalog.pricing import resolve_rate
from central.billing.catalog.public_ips import get_public_ipv4_rates
from central.billing.catalog.subscriptions import server_segments
from central.billing.doctype.subscription_change.subscription_change import (
	RATED_CHANGE_TYPES,
	SEGMENT_CHANGE_TYPES,
)
from central.billing.doctype.usage_segment.usage_segment import get_last_segment
from central.billing.platform.jobs import each_isolated
from central.billing.platform.records import save_billing_record
from central.billing.revenue import usage_month
from central.billing.revenue.usage_ledger import utc_day_start, utc_day_window, utc_today
from central.billing.revenue.usage_month import month_of
from central.billing.revenue.usage_month_days import subjects_with_day
from central.services.doctype.service.service import NETWORK_SERVICE, PUBLIC_IPV4_METER, ensure_services

DOCTYPE = "Usage Segment"
STATE = "State"
STATE_REPORT = "State Report"
TERMINATION = "Termination"
OPERATOR = "Operator"
MIGRATION = "Migration"
# The source a projected day slot names; the slot also names the segment it came from.
SEGMENT = "Segment"
PAGE_SIZE = 500


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
	# A state change is recorded as the system, whoever made the save that carried it.
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


def count_addresses(public_ipv4: str | None) -> int:
	"""The public IPv4 addresses a server holds. Its one field holds at most one today."""
	return 1 if public_ipv4 else 0


def record_public_ipv4(server: Document) -> None:
	"""Record the public IPv4 addresses a server holds from when the region saw them, and none once it ends."""
	is_terminated = server.status == "Terminated"
	held = 0 if is_terminated else count_addresses(server.public_ipv4)
	is_observed = bool(server.state_observed_at) and server.has_value_changed("state_observed_at")
	# The region's clock, so a report that lands late still starts the segment when the change happened.
	at = server.state_observed_at if is_observed else frappe.utils.now_datetime()
	source = _source_of(is_terminated, is_observed)
	reference = str(server.last_reported_at or server.state_observed_at) if is_observed else None
	set_quantity(NETWORK_SERVICE, PUBLIC_IPV4_METER, server, held, at, source, reference)


def _source_of(is_terminated: bool, is_observed: bool) -> str:
	if is_terminated:
		return TERMINATION
	# A save that carries no region report is an operator's edit.
	return STATE_REPORT if is_observed else OPERATOR


def start_on_install() -> None:
	"""Bill public IPv4 from the day a fresh site is installed."""
	# A fresh install marks the cutover patch done without running it, and holds no
	# per-address subscription, so its days can start at once.
	# Called again here so the service exists whatever order the install hooks run in.
	ensure_services()
	if not cutover_day():
		frappe.db.set_value("Service", NETWORK_SERVICE, "bill_from", utc_today())


def cutover_day() -> datetime.date | None:
	"""The first UTC day public IPv4 bills on its server, or None before the cutover."""
	bill_from = frappe.db.get_value("Service", NETWORK_SERVICE, "bill_from")
	return frappe.utils.getdate(bill_from) if bill_from else None


def held_addresses() -> dict[str, int]:
	"""Each server that holds a public IPv4 now, with how many it holds."""
	rows = frappe.get_all(
		"Virtual Machine",
		filters={"public_ipv4": ["is", "set"], "status": ["!=", "Terminated"]},
		fields=["name", "public_ipv4"],
	)
	return {row.name: count_addresses(row.public_ipv4) for row in rows}


def find_unbilled_addresses() -> list[tuple[frappe._dict, str]]:
	"""Each billed server holding an address that has no price in its team's currency for its region."""
	servers = open_subjects(NETWORK_SERVICE, PUBLIC_IPV4_METER)
	if not servers:
		return []
	rates = get_public_ipv4_rates()
	return [
		(
			segment,
			f"Holds a public IPv4 with no price in {segment.currency} for {segment.cluster}, so its draft invoice is held.",
		)
		for segment in server_segments(servers)
		if resolve_rate(rates, segment.currency, segment.cluster) is None
	]


def project_team(team: str, period_end) -> int:
	"""Write the state days of a team's subjects for the month a draft bills and the month before."""
	until = frappe.utils.getdate(period_end)
	# A day of the month before can land after that month closed, and still bills in this draft.
	since = frappe.utils.add_months(month_of(until), -1)
	subjects = _team_subjects(team, since, until)
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


def held_days(segments: list, windows: dict[str, list], days: list[tuple]) -> dict[tuple, frappe._dict]:
	"""The most each subject held at once on each day while it was billed, by (subject, day)."""
	found: dict[tuple, frappe._dict] = {}
	for segment in segments:
		for window in windows.get(segment.subject, []):
			start = max(segment.starts_at, window.start)
			end = min(segment.ends_at or datetime.datetime.max, window.end or datetime.datetime.max)
			# Held and billed at the same moment, not only on the same day.
			if start < end:
				_add_days(found, segment, window, (start, end), days)
	return found


def _project_pages(subjects: list[str], since, until) -> int:
	"""Project the subjects one page at a time, so a failed page never stops the rest."""
	names = sorted(set(subjects))
	pages = {names[start]: names[start : start + PAGE_SIZE] for start in range(0, len(names), PAGE_SIZE)}
	counts = each_isolated(
		"Usage segment days",
		"Virtual Machine",
		list(pages),
		lambda first: project(pages[first], since, until),
	)
	return sum(counts)


def _billed_windows(servers: list[str], before) -> dict[str, list]:
	"""Each server's billed stretches before `before`, from the change that opened billing to the one that closed it."""
	windows: dict[str, list] = {}
	opened: dict[str, frappe._dict] = {}
	for row in _server_changes(servers, before):
		if row.change_type in RATED_CHANGE_TYPES:
			# A plan change while billed keeps the same stretch open.
			opened.setdefault(row.subscription, row)
		elif first := opened.pop(row.subscription, None):
			windows.setdefault(row.server, []).append(_window(first, row.effective_at))
	for first in opened.values():
		windows.setdefault(first.server, []).append(_window(first, None))
	return windows


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
	windows = _billed_windows(list({segment.subject for segment in segments}), before)
	meter = frappe.get_doc("Service", service).get_meter(meter_key)
	now = frappe.utils.now_datetime()
	return [
		meter.get_day_row(found, day, found.quantity, dimension="", as_of=now, segment=found.segment)
		for (_, day), found in held_days(segments, windows, _utc_days(since, until)).items()
	]


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
	"""Whether the segment beats the day's kept value: more held, or as much on a later subscription."""
	if not kept:
		return True
	quantity = frappe.utils.flt(segment.quantity)
	return quantity > kept.quantity or (quantity == kept.quantity and window.start > kept.billed_from)


def _window(first, end) -> frappe._dict:
	return frappe._dict(subscription=first.subscription, team=first.team, start=first.effective_at, end=end)


def _server_changes(servers: list[str], before) -> list:
	"""The changes that open or close billing on the servers' subscriptions, oldest first."""
	if not servers:
		return []
	change = frappe.qb.DocType("Subscription Change")
	subscription = frappe.qb.DocType("Subscription")
	return (
		frappe.qb.from_(change)
		.join(subscription)
		.on(change.subscription == subscription.name)
		.select(subscription.server_id.as_("server"), subscription.team, change.subscription)
		.select(change.change_type, change.effective_at)
		.where(subscription.server_id.isin(servers))
		.where(change.change_type.isin(list(SEGMENT_CHANGE_TYPES)))
		.where(change.effective_at < before)
		.orderby(change.effective_at, order=Order.asc)
		.orderby(change.creation, order=Order.asc)
	).run(as_dict=True)


def _segments_of(subjects: list[str], since, until) -> dict[tuple, list]:
	"""The segments of the subjects held at some moment from `since` to `until`, by service and meter."""
	if not subjects:
		return {}
	table = frappe.qb.DocType(DOCTYPE)
	rows = (
		frappe.qb.from_(table)
		.select(table.name, table.service, table.meter, table.subject, table.quantity)
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


def _changed_subjects(since) -> list[str]:
	"""The subjects of the segments opened or closed since `since`."""
	return frappe.get_all(DOCTYPE, filters={"modified": [">", since]}, pluck="subject", distinct=True)


def _subjects_without_day(today) -> list[str]:
	"""The subjects that hold a state now and have no value for today yet."""
	rows = frappe.get_all(DOCTYPE, filters={"ends_at": ["is", "not set"]}, fields=["service", "subject"])
	by_service: dict[str, set] = {}
	for row in rows:
		by_service.setdefault(row.service, set()).add(row.subject)
	return [
		subject
		for service, subjects in by_service.items()
		for subject in subjects - subjects_with_day(service, today)
	]
