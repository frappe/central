# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The public IPv4 addresses a server holds, as one Level Usage Day per UTC day on its subscription."""

import datetime

import frappe

from central.billing.catalog.pricing import resolve_rate
from central.billing.catalog.public_ips import get_public_ipv4_rates
from central.billing.revenue.bundled_buckets import server_segments
from central.billing.revenue.usage_ledger import utc_day_window, utc_today, write_days
from central.services.doctype.service.service import NETWORK_SERVICE, PUBLIC_IPV4_METER

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
	days = [today]
	if frappe.db.get_default(SWEPT_DAY) != str(today):
		# The first run of a UTC day closes the day before, so the hours the scheduler missed still count.
		days.append(today - datetime.timedelta(days=1))
	written = sum(write_ipv4_days(day, held) for day in days)
	frappe.db.set_default(SWEPT_DAY, str(today))
	return written


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
	meter = frappe.get_doc("Service", NETWORK_SERVICE).get_meter(PUBLIC_IPV4_METER)
	names = [name for name, addresses in held.items() if addresses > 0]
	written = 0
	for start in range(0, len(names), PAGE_SIZE):
		billed = billed_servers_on(day, names[start : start + PAGE_SIZE])
		rows = [_day_row(meter, segment, day, held[server]) for server, segment in billed.items()]
		written += write_days(rows).count
	return written


def billed_servers_on(day, servers: list[str]) -> dict[str, frappe._dict]:
	"""Each of `servers` whose subscription had an open segment at some moment of the UTC day `day`, by server."""
	# A trial server has no subscription yet, and a day its billing stayed paused has no open moment.
	return {segment.server_id: segment for segment in server_segments(servers, utc_day_window(day))}


def find_unbilled_addresses() -> list[tuple[frappe._dict, str]]:
	"""Each billed server holding an address with no price for it or no day for yesterday, and why."""
	servers = list(held_addresses())
	if not servers:
		return []
	return [*_unpriced(servers), *_unrecorded(servers)]


def _unpriced(servers: list[str]) -> list[tuple[frappe._dict, str]]:
	rates = get_public_ipv4_rates()
	return [
		(
			segment,
			f"Holds a public IPv4 with no price in {segment.currency} for {segment.cluster}, so its draft invoice is held.",
		)
		for segment in server_segments(servers)
		if resolve_rate(rates, segment.currency, segment.cluster) is None
	]


def _unrecorded(servers: list[str]) -> list[tuple[frappe._dict, str]]:
	yesterday = utc_today() - datetime.timedelta(days=1)
	recorded = set(
		frappe.get_all(
			"Usage Day",
			filters={"service": NETWORK_SERVICE, "day": yesterday, "subject": ["in", servers]},
			pluck="subject",
		)
	)
	return [
		(segment, f"Holds a public IPv4 with no usage for {yesterday} (UTC), so that day bills nothing.")
		for server, segment in billed_servers_on(yesterday, servers).items()
		if server not in recorded
	]


def _day_row(meter, segment, day, addresses: int) -> dict:
	subject = frappe._dict(
		external_id=segment.server_id, team=segment.team, subscription=segment.subscription
	)
	return meter.get_day_row(subject, day, addresses, included=0, as_of=frappe.utils.now_datetime())
