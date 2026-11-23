# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The backup bucket that comes with a server whose plan includes storage.

Pilot creates it in Cargo with no cap and no Team Service. It is billed on the server's own
subscription; the plan's Storage is its bundle.
"""

import datetime

import frappe

from central.billing.catalog.subscriptions import active_segments
from central.billing.revenue.bundles import included_by_plan
from central.billing.revenue.usage_ledger import utc_day_start
from central.services.doctype.service.service import STORAGE_SERVICE
from central.services.doctype.team_service.team_service import billed_subjects, bucket_name_for


def bundled_buckets(names: list[str] | None = None) -> dict[str, frappe._dict]:
	"""The backup bucket of every server billing now whose plan includes storage."""
	buckets = _all_bundled_buckets()
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
	# A server billing at either edge billed part of the day; the bundle is the one it ended on.
	return {**_all_bundled_buckets(start), **_all_bundled_buckets(end)}


def _all_bundled_buckets(at=None) -> dict[str, frappe._dict]:
	included = included_by_plan("Storage")
	if not included:
		return {}
	segments = _segments_with_storage(included, at)
	servers = _servers([segment.server_id for segment in segments])
	tenants = _tenants({segment.team for segment in segments})
	rows = [_bucket(segment, servers, tenants, included) for segment in segments]
	return {row.external_id: row for row in rows if row}


def _segments_with_storage(included: dict, at) -> list:
	"""The open server segments, now or at `at`, whose plan includes storage."""
	filters = {"server_id": ["is", "set"]}
	if at is None:
		filters["plan"] = ["in", list(included)]
	# A paused or ended server has no open segment, so its bucket bills nothing. A past moment
	# takes the plan the server ran then, which a resize may have changed since.
	return [segment for segment in active_segments(filters, at=at) if segment.plan in included]


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
		included=included[segment.plan],
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
