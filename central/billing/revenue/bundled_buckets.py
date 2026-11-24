# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The backup bucket that comes with a server whose plan includes storage.

Pilot creates it in Cargo with no cap and no Team Service. It is billed on the server's own
subscription; the Storage its plan or composed shape includes is its bundle.
"""

import datetime

import frappe
from frappe.query_builder import Order

from central.billing.catalog.subscriptions import active_segments
from central.billing.doctype.subscription_change.subscription_change import (
	RATED_CHANGE_TYPES,
	SEGMENT_CHANGE_TYPES,
)
from central.billing.revenue.bundles import Bundles
from central.billing.revenue.usage_ledger import utc_day_start
from central.services.doctype.service.service import STORAGE_SERVICE
from central.services.doctype.team_service.team_service import billed_subjects, bucket_name_for


def bundled_buckets(names: list[str] | None = None, day=None) -> dict[str, frappe._dict]:
	"""The backup bucket of every server billing now, or on `day`, whose plan includes storage."""
	buckets = _bundled_buckets_on(day)
	if names is None:
		return buckets
	return {name: buckets[name] for name in names if name in buckets}


def billed_storage_subjects(day=None) -> dict[str, frappe._dict]:
	"""Every bucket storage bills, the team's own and the servers' backup buckets, by bucket name."""
	return {**billed_subjects(STORAGE_SERVICE), **_bundled_buckets_on(day)}


def billed_subjects_of(service: str, day=None) -> dict[str, frappe._dict]:
	"""Every subject a service bills; a server's backup bucket only while the server bills on `day`."""
	if service == STORAGE_SERVICE:
		return billed_storage_subjects(day)
	return billed_subjects(service)


def _bundled_buckets_on(day) -> dict[str, frappe._dict]:
	"""The backup buckets of servers billing now, or at any point of the UTC day `day`."""
	if day is None:
		return _all_bundled_buckets()
	day = frappe.utils.getdate(day)
	start, end = utc_day_start(day), utc_day_start(day + datetime.timedelta(days=1))
	return _all_bundled_buckets((start, end))


def _all_bundled_buckets(during=None) -> dict[str, frappe._dict]:
	# A paused or ended server has no open segment, so its bucket bills nothing.
	segments, included = _segments_with_storage(during)
	servers = _servers([segment.server_id for segment in segments])
	tenants = _tenants({segment.team for segment in segments})
	rows = [_bucket(segment, servers, tenants, included) for segment in segments]
	return {row.external_id: row for row in rows if row}


def _segments_with_storage(during) -> tuple[list, dict[str, float]]:
	"""The server segments open now, or at some moment of `during`, with a storage bundle; and the bundles."""
	segments = active_segments({"server_id": ["is", "set"]}, during=during)
	included = _bundles_now(segments) if during is None else _bundles_during(segments, during)
	return [segment for segment in segments if included.get(segment.subscription)], included


def _bundles_now(segments: list) -> dict[str, float]:
	"""Each subscription's storage bundle on the plan or composed shape it is billed on now."""
	bundles = Bundles("Storage", segments)
	return {segment.subscription: bundles.of(segment) for segment in segments}


def _bundles_during(segments: list, during: tuple) -> dict[str, float]:
	"""Each subscription's storage bundle on a past day: the last segment open in it that has one."""
	candidates = _segments_in(segments, during)
	bundles = Bundles("Storage", [c for rows in candidates.values() for c in rows])
	return {name: _first_bundle(bundles, rows) for name, rows in candidates.items()}


def _first_bundle(bundles, rows: list) -> float:
	return next((found for found in (bundles.of(row) for row in rows) if found), 0)


def _segments_in(segments: list, during: tuple) -> dict[str, list]:
	"""The rated segments open at some moment of `during`, newest first, per subscription."""
	start, end = during
	rows = _changes_before(end, [segment.subscription for segment in segments])
	plans = _plan_names({row.new_value for row in rows if row.new_value})
	open_in: dict[str, list] = {}
	settled = set()
	for row in rows:
		if row.subscription in settled:
			continue
		# The change in force at the start ends the walk; it counts only when it opened a segment.
		if row.effective_at <= start:
			settled.add(row.subscription)
		if row.change_type in RATED_CHANGE_TYPES:
			open_in.setdefault(row.subscription, []).append(_segment(row, plans))
	return open_in


def _segment(row, plans: set) -> frappe._dict:
	plan = row.new_value if row.new_value in plans else None
	return frappe._dict(subscription=row.subscription, plan=plan, included_resources=row.included_resources)


def _changes_before(end, names: list[str]) -> list:
	if not names:
		return []
	change = frappe.qb.DocType("Subscription Change")
	return (
		frappe.qb.from_(change)
		.select(
			change.subscription,
			change.change_type,
			change.new_value,
			change.included_resources,
			change.effective_at,
		)
		.where(change.subscription.isin(names))
		.where(change.change_type.isin(list(SEGMENT_CHANGE_TYPES)))
		.where(change.effective_at < end)
		.orderby(change.effective_at, order=Order.desc)
		.orderby(change.creation, order=Order.desc)
	).run(as_dict=True)


def _plan_names(labels: set) -> set:
	return (
		set(frappe.get_all("Plan", filters={"name": ["in", list(labels)]}, pluck="name")) if labels else set()
	)


def _bucket(segment, servers: dict, tenants: dict, included: dict) -> frappe._dict | None:
	server, tenant = servers.get(segment.server_id), tenants.get(segment.team)
	if not (server and tenant):
		return None
	return frappe._dict(
		name=segment.server_id,
		external_id=bucket_name_for(tenant, server.region, segment.server_id),
		team=segment.team,
		subscription=segment.subscription,
		region=server.region,
		creation=server.creation,
		included=included[segment.subscription],
	)


def _servers(names: list[str]) -> dict:
	rows = frappe.get_all(
		"Virtual Machine", filters={"name": ["in", names]}, fields=["name", "region", "creation"]
	)
	return {row.name: row for row in rows}


def _tenants(teams: set[str]) -> dict:
	rows = frappe.get_all(
		"Team",
		filters={"name": ["in", list(teams)], "tenant_id": ["is", "set"]},
		fields=["name", "tenant_id"],
	)
	return {row.name: row.tenant_id for row in rows}
