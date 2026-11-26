# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The public IPv4 addresses a server holds, as one Level Usage Day per UTC day on its subscription."""

import datetime

import frappe
from frappe.query_builder import Order

from central.billing.catalog.pricing import resolve_rate
from central.billing.catalog.public_ips import get_public_ipv4_rates
from central.billing.catalog.subscriptions import server_segments
from central.billing.doctype.subscription_change.subscription_change import (
	CLOSING_CHANGE_TYPES,
	RATED_CHANGE_TYPES,
	SEGMENT_CHANGE_TYPES,
)
from central.billing.platform.jobs import each_isolated
from central.billing.revenue.usage_ledger import utc_day_window, utc_today, write_days
from central.services.doctype.service.service import NETWORK_SERVICE, PUBLIC_IPV4_METER, ensure_services

SWEPT_DAY = "public_ipv4_swept_day"
PAGE_SIZE = 500


def count_addresses(public_ipv4: str | None) -> int:
	"""The public IPv4 addresses a server holds. Its one field holds at most one today."""
	return 1 if public_ipv4 else 0


def queue_today(server: str, addresses: int) -> None:
	"""Write today's day for a server Atlas reports an address on, once the report commits."""
	from central.billing.revenue.invoicing.run import billing_queue

	day = utc_today()
	frappe.enqueue(
		"central.billing.revenue.public_ipv4_usage.write_server_day",
		queue=billing_queue(),
		job_id=f"public_ipv4_day::{server}::{day}",
		deduplicate=True,
		enqueue_after_commit=True,
		server=server,
		day=str(day),
		addresses=addresses,
	)


def write_server_day(server: str, day: str, addresses: int) -> int:
	"""Write one server's day with the addresses it was reported to hold."""
	# The count comes from the report, so an address released before this job runs still bills its day.
	return write_ipv4_days(day, {server: addresses})


def read_public_ipv4() -> int:
	"""Hourly: write today's day for each server holding an address, and yesterday's on a UTC day's first run."""
	today = utc_today()
	held = held_addresses()
	written, _ = _sweep(today, held)
	if frappe.db.get_default(SWEPT_DAY) == str(today):
		return written
	# The first run of a UTC day closes the day before, so the hours the scheduler missed still count.
	closed, is_complete = _sweep(today - datetime.timedelta(days=1), held)
	if is_complete:
		# A failed page leaves the mark unset, so the next run writes the day before again.
		frappe.db.set_default(SWEPT_DAY, str(today))
	return written + closed


def start_on_install() -> None:
	"""Bill public IPv4 per day from the day a fresh site is installed."""
	# A fresh install marks the cutover patch done without running it, and holds no
	# per-address subscription, so its days can start at once.
	# Called again here so the service exists whatever order the install hooks run in.
	ensure_services()
	if not cutover_day():
		frappe.db.set_value("Service", NETWORK_SERVICE, "bill_from", utc_today())


def cutover_day() -> datetime.date | None:
	"""The first UTC day public IPv4 bills per day, or None before the cutover."""
	# Before migrate the service may not exist, and before the cutover the per-address
	# subscriptions still bill, so either way no day may be written.
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


def write_ipv4_days(day, held: dict[str, int]) -> int:
	"""Write one Usage Day for each server in `held` that billed at some moment of the UTC day `day`."""
	pages = _pages(held)
	write_page = _page_writer(day, pages, held)
	return sum(write_page(first) for first in pages)


def billed_servers_on(day, servers: list[str]) -> dict[str, frappe._dict]:
	"""Each of `servers` whose subscription had an open segment at some moment of the UTC day `day`, by server."""
	# A trial server has no subscription yet, and a day its billing stayed paused has no open moment.
	return {segment.server_id: segment for segment in server_segments(servers, utc_day_window(day))}


def billed_per_address(day, servers: list[str]) -> set[str]:
	"""The servers whose per-address IPv4 subscription billed some hour of the UTC day `day`."""
	start, end = utc_day_window(day)
	closed = {row.subscription for row in _address_changes(servers, CLOSING_CHANGE_TYPES, start, end)}
	if not closed:
		return set()
	billed, previous = set(), {}
	for row in _address_changes(servers, SEGMENT_CHANGE_TYPES, None, end):
		if row.subscription in closed and _is_end_of_billed_segment(
			previous.get(row.subscription), row, start
		):
			billed.add(row.server)
		previous[row.subscription] = row
	return billed


def find_unbilled_addresses() -> list[tuple[frappe._dict, str]]:
	"""Each billed server holding an address that has no price in its team's currency for its region."""
	servers = list(held_addresses())
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


def _sweep(day, held: dict[str, int]) -> tuple[int, bool]:
	"""Write `day` one page at a time, so a failed page never stops the rest; and whether every page wrote."""
	pages = _pages(held)
	counts = each_isolated(
		f"Public IPv4 day {day}", "Virtual Machine", list(pages), _page_writer(day, pages, held)
	)
	return sum(counts), len(counts) == len(pages)


def _pages(held: dict[str, int]) -> dict[str, list[str]]:
	"""The servers that hold an address, in pages keyed by their first server."""
	names = [name for name, addresses in held.items() if addresses > 0]
	pages = [names[start : start + PAGE_SIZE] for start in range(0, len(names), PAGE_SIZE)]
	return {page[0]: page for page in pages}


def _page_writer(day, pages: dict[str, list[str]], held: dict[str, int]):
	"""Write `day` for the page that starts with a given server."""
	cutover = cutover_day()
	if not cutover:
		# Every page "writes" nothing, so the sweep still marks the day before as swept. That
		# day is before the cutover, which writes it off, so nothing is lost.
		return lambda first: 0
	meter = frappe.get_doc("Service", NETWORK_SERVICE).get_meter(PUBLIC_IPV4_METER)
	# Per-address subscriptions all closed by the cutover day, so no later day can overlap one.
	is_cutover_day = frappe.utils.getdate(day) == cutover

	def write_page(first: str) -> int:
		servers = pages[first]
		billed = billed_servers_on(day, servers)
		# An hour a per-address subscription billed is not billed again as a day.
		skipped = billed_per_address(day, servers) if is_cutover_day else set()
		rows = [
			_day_row(meter, segment, day, held[server])
			for server, segment in billed.items()
			if server not in skipped
		]
		return write_days(rows).count

	return write_page


def _address_changes(servers: list[str], types, after, before) -> list:
	"""The segment changes of the servers' per-address subscriptions of `types`, oldest first."""
	change = frappe.qb.DocType("Subscription Change")
	subscription = frappe.qb.DocType("Subscription")
	query = (
		frappe.qb.from_(change)
		.join(subscription)
		.on(change.subscription == subscription.name)
		.select(subscription.public_ip_server.as_("server"), change.subscription)
		.select(change.change_type, change.effective_at)
		.where(subscription.public_ip_server.isin(servers))
		.where(change.change_type.isin(list(types)))
		.where(change.effective_at < before)
		.orderby(change.effective_at, order=Order.asc)
		.orderby(change.creation, order=Order.asc)
	)
	if after is not None:
		query = query.where(change.effective_at > after)
	return query.run(as_dict=True)


def _is_end_of_billed_segment(previous, row, start) -> bool:
	"""Whether `row` closes, after `start`, a segment that was open for some time."""
	if row.change_type not in CLOSING_CHANGE_TYPES or row.effective_at <= start:
		return False
	# A segment opened and closed at the same moment billed no hour.
	return (
		bool(previous)
		and previous.change_type in RATED_CHANGE_TYPES
		and previous.effective_at < row.effective_at
	)


def _day_row(meter, segment, day, addresses: int) -> dict:
	subject = frappe._dict(
		external_id=segment.server_id, team=segment.team, subscription=segment.subscription
	)
	return meter.get_day_row(subject, day, addresses, included=0, as_of=frappe.utils.now_datetime())
