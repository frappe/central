# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The backup bucket that comes with a server whose plan includes storage.

Pilot creates it in Cargo with no cap and no Team Service. It is billed on the server's own
subscription; the plan's Storage is its bundle.
"""

import frappe

from central.billing.catalog.subscriptions import active_segments
from central.billing.revenue.bundles import included_by_plan
from central.services.doctype.service.service import STORAGE_SERVICE
from central.services.doctype.team_service.team_service import billed_subjects, bucket_name_for


def bundled_buckets(names: list[str] | None = None) -> dict[str, frappe._dict]:
	"""The backup bucket of every billed server whose plan includes storage, by bucket name."""
	buckets = _all_bundled_buckets()
	if names is None:
		return buckets
	return {name: buckets[name] for name in names if name in buckets}


def billed_storage_subjects() -> dict[str, frappe._dict]:
	"""Every bucket storage bills, the team's own and the servers' backup buckets, by bucket name."""
	return {**billed_subjects(STORAGE_SERVICE), **bundled_buckets()}


def billed_subjects_of(service: str) -> dict[str, frappe._dict]:
	"""Every subject a service bills, a storage service's backup buckets too."""
	if service == STORAGE_SERVICE:
		return billed_storage_subjects()
	return billed_subjects(service)


def _all_bundled_buckets() -> dict[str, frappe._dict]:
	included = included_by_plan("Storage")
	if not included:
		return {}
	# A paused or ended server has no open segment, so its bucket bills nothing.
	segments = active_segments({"server_id": ["is", "set"], "plan": ["in", list(included)]})
	servers = _servers([segment.server_id for segment in segments])
	tenants = _tenants({segment.team for segment in segments})
	rows = [_bucket(segment, servers, tenants, included) for segment in segments]
	return {row.external_id: row for row in rows if row}


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
