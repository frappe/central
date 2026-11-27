import datetime

import frappe
from frappe.query_builder import Order

from central.billing.doctype.subscription_change.subscription_change import (
	CLOSING_CHANGE_TYPES,
	RATED_CHANGE_TYPES,
	SEGMENT_CHANGE_TYPES,
)
from central.billing.revenue import public_ipv4, usage_segments
from central.billing.revenue.usage_ledger import utc_day_start, utc_day_window, utc_today
from central.billing.revenue.usage_month import DAY_FIELDS, STATE, days_of, month_of
from central.billing.revenue.usage_month_days import day_rows
from central.services.doctype.service.service import NETWORK_SERVICE, PUBLIC_IPV4_METER, ensure_services

PATCH = "central.patches.v0_0.move_public_ipv4_to_segments"
SWEPT_DAY = "public_ipv4_swept_day"
ONE_DAY = datetime.timedelta(days=1)


def execute():
	"""Keep public IPv4 as segments: one per run of billed days, and an open one for each address held now."""
	ensure_services()
	today, now = utc_today(), frappe.utils.now_datetime()
	cutover = public_ipv4.cutover_day()
	if not frappe.db.exists("Usage Segment", {"service": NETWORK_SERVICE, "meter": PUBLIC_IPV4_METER}):
		SegmentMigration(cutover, today, now).run()
	set_state_meter()
	frappe.defaults.clear_default(SWEPT_DAY)
	if cutover:
		reproject(cutover, today)


class SegmentMigration:
	"""Turns the public IPv4 days a server billed into its segments."""

	def __init__(self, cutover: datetime.date | None, today: datetime.date, now: datetime.datetime):
		self.cutover, self.today, self.now = cutover, today, now
		self.billed = billed_days()
		self.holders = public_ipv4.held_addresses()
		self.teams = {**self.billed.teams, **_server_teams(list(self.holders))}
		without_cutover_day = [name for name in self.holders if (name, cutover) not in self.billed.days]
		self.late = starts_late(cutover, today, without_cutover_day)

	def run(self) -> None:
		for subject in sorted(self.billed.subjects | set(self.holders)):
			runs = runs_of(self.billed.days, subject)
			if subject in self.holders:
				self.write_holder(subject, runs)
			else:
				self.write_runs(subject, runs)

	def write_holder(self, subject: str, runs: list) -> None:
		"""Close the runs of a server that holds an address now, and keep its last run open if it reaches yesterday."""
		if runs and runs[-1][1] >= self.today - ONE_DAY:
			# Those days were written while the address was held, so it is still the same holding.
			self.write_runs(subject, runs[:-1])
			first, _, value = runs[-1]
			self.insert(subject, value, utc_day_start(first))
			return
		self.write_runs(subject, runs)
		self.insert(subject, self.holders[subject], self.get_opened_at(subject))

	def get_opened_at(self, subject: str) -> datetime.datetime:
		"""When a holder with no recent run starts: now, or the day after the cutover where the old subscription billed it."""
		if subject in self.late:
			return max(self.now, utc_day_start(self.cutover + ONE_DAY))
		return self.now

	def write_runs(self, subject: str, runs: list) -> None:
		for first, last, value in runs:
			# A run that reaches today ends now, so the segment never records the future.
			self.insert(subject, value, utc_day_start(first), min(utc_day_start(last + ONE_DAY), self.now))

	def insert(self, subject: str, quantity: float, starts_at, ends_at=None) -> None:
		closed = {"closed_source": usage_segments.MIGRATION, "closed_reference": PATCH} if ends_at else {}
		usage_segments.insert_segment(
			service=NETWORK_SERVICE,
			meter=PUBLIC_IPV4_METER,
			subject=subject,
			subject_doctype="Virtual Machine",
			team=self.teams[subject],
			quantity=quantity,
			starts_at=starts_at,
			ends_at=ends_at,
			opened_source=usage_segments.MIGRATION,
			opened_reference=PATCH,
			closed_by=frappe.session.user if ends_at else None,
			**closed,
		)


def billed_days() -> frappe._dict:
	"""Every billed public IPv4 day by (server, day) with its value, and each server's team."""
	rows = frappe.get_all(
		"Usage Month",
		filters={"service": NETWORK_SERVICE, "meter": PUBLIC_IPV4_METER},
		fields=["subject", "team", "month", "filled", "written_off", *DAY_FIELDS],
		order_by="month asc",
	)
	days, teams = {}, {}
	for row in rows:
		teams.setdefault(row.subject, row.team)
		# A written-off day came before the cutover and billed nothing.
		for day in days_of(row.filled & ~row.written_off):
			key = (row.subject, row.month.replace(day=day))
			days[key] = max(days.get(key, 0), frappe.utils.flt(row[DAY_FIELDS[day - 1]]))
	return frappe._dict(days=days, teams=teams, subjects={subject for subject, _ in days})


def runs_of(days: dict, subject: str) -> list[list]:
	"""The server's runs of consecutive days that held the same value, oldest first, as [first, last, value]."""
	runs = []
	for day in sorted(day for name, day in days if name == subject):
		value = days[(subject, day)]
		if runs and runs[-1][1] + ONE_DAY == day and runs[-1][2] == value:
			runs[-1][1] = day
		else:
			runs.append([day, day, value])
	return runs


def starts_late(cutover, today: datetime.date, servers: list[str]) -> set[str]:
	"""The holders that start the day after the cutover, as their per-address subscription billed some of it."""
	# Only a segment opened on the cutover day can reach an hour the old subscription already billed.
	if not (cutover and servers and today == cutover):
		return set()
	return billed_per_address(cutover, servers)


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


def set_state_meter() -> None:
	"""Mark the public IPv4 meter and its month rows as a state meter."""
	frappe.db.set_value(
		"Service Meter",
		{"parent": NETWORK_SERVICE, "meter_key": PUBLIC_IPV4_METER},
		"aggregation",
		STATE,
	)
	table = frappe.qb.DocType("Usage Month")
	(
		frappe.qb.update(table)
		.set(table.aggregation, STATE)
		.where((table.service == NETWORK_SERVICE) & (table.meter == PUBLIC_IPV4_METER))
	).run()


def reproject(cutover: datetime.date, today: datetime.date) -> int:
	"""Write the open months from the segments, and log each day that changed. None is expected."""
	since = max(cutover, frappe.utils.add_months(month_of(today), -1))
	subjects = frappe.get_all(
		"Usage Segment",
		filters={"service": NETWORK_SERVICE, "meter": PUBLIC_IPV4_METER},
		pluck="subject",
		distinct=True,
		order_by="subject asc",
	)
	before = _day_values(subjects)
	for start in range(0, len(subjects), usage_segments.PAGE_SIZE):
		usage_segments.project(subjects[start : start + usage_segments.PAGE_SIZE], since, today)
	changed = sorted(key for key, value in _day_values(subjects).items() if before.get(key) != value)
	if changed:
		frappe.logger("billing").warning(f"Public IPv4 segments changed {len(changed)} days: {changed[:50]}")
	return len(changed)


def _day_values(subjects: list[str]) -> dict[tuple, float]:
	"""Each day's value by server, subscription and day, so a day that moved subscription shows too."""
	if not subjects:
		return {}
	rows = day_rows({"service": NETWORK_SERVICE, "meter": PUBLIC_IPV4_METER, "subject": ["in", subjects]})
	return {(row.subject, row.subscription, row.day): row.quantity for row in rows}


def _server_teams(servers: list[str]) -> dict[str, str]:
	rows = frappe.get_all("Virtual Machine", filters={"name": ["in", servers]}, fields=["name", "team"])
	return {row.name: row.team for row in rows}


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
