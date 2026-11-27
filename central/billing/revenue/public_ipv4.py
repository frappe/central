# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The public IPv4 addresses a server holds, recorded as a state meter on the network service."""

import datetime

import frappe
from frappe.model.document import Document

from central.billing.catalog.pricing import resolve_rate
from central.billing.catalog.public_ips import get_public_ipv4_rates
from central.billing.catalog.subscriptions import server_segments
from central.billing.revenue.usage_ledger import utc_today
from central.billing.revenue.usage_segments import (
	OPERATOR,
	STATE_REPORT,
	TERMINATION,
	open_subjects,
	set_quantity,
)
from central.services.doctype.service.service import NETWORK_SERVICE, PUBLIC_IPV4_METER, ensure_services


def count_addresses(public_ipv4: str | None) -> int:
	"""The public IPv4 addresses a server holds. Its one field holds at most one today."""
	return 1 if public_ipv4 else 0


def record_public_ipv4(server: Document) -> None:
	"""Record the public IPv4 addresses a server holds from when Central received the report, and none once it ends."""
	is_terminated = server.status == "Terminated"
	held = 0 if is_terminated else count_addresses(server.public_ipv4)
	is_observed = bool(server.state_observed_at) and server.has_value_changed("state_observed_at")
	# state_observed_at is when Central received the report, not the region's clock.
	at = server.state_observed_at if is_observed else frappe.utils.now_datetime()
	source = _source_of(is_terminated, is_observed)
	reference = _report_reference(server) if is_observed else None
	set_quantity(NETWORK_SERVICE, PUBLIC_IPV4_METER, server, held, at, source, reference)


def _report_reference(server: Document) -> str:
	"""The region's time of the report that this save carries, else when Central received it."""
	# A polled read leaves last_reported_at as it was, so an older webhook's time would be wrong here.
	if server.last_reported_at and server.has_value_changed("last_reported_at"):
		return str(server.last_reported_at)
	return str(server.state_observed_at)


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
