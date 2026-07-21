from __future__ import annotations

import frappe
from frappe import _
from frappe.query_builder import DocType, Order
from pypika import analytics as an

from central.iam import can, resolve_team

# Rows returned per region by list_site_groups. The count is exact regardless — a
# region with more sites lists this many and reports the true total, so the map
# payload stays bounded however many sites a team runs.
SITE_PREVIEW_LIMIT = 50

# A team's resources unified for the console home + resource-aware landing: servers
# (the Asset mirror) and sites (the Site mirror), each tagged with `kind`. "Asset" as
# the umbrella term is deferred to a later Asset->Server rename; "resource" is the
# interim word. Gated on server:view — every role that reaches the home carries it.


@frappe.whitelist(methods=["GET"])
def list_resources(team: str | None = None, kind: str | None = None) -> dict:
	"""A team's servers and sites as one list, so the console lands a single-site team
	on its site and a server owner on their servers from one read (optionally one `kind`). Each carries a region
	so both share the map view."""
	user = frappe.session.user
	team = resolve_team(user, team)
	if not can(user, team, "server:view"):
		frappe.throw(_("You can't view this team's resources."), frappe.PermissionError)

	servers = (
		frappe.get_all(
			"Asset",
			filters={"team": team},
			fields=["name", "title", "resource_id", "status", "public_ipv4", "cluster"],
			order_by="title",
		)
		if kind in (None, "server")
		else []
	)
	sites = (
		frappe.get_all("Site", filters={"team": team}, fields=["name", "status", "url", "region"], order_by="name")
		if kind in (None, "site")
		else []
	)

	# Servers carry a cluster, not a region — resolve every cluster's region in one query.
	clusters = {row.cluster for row in servers if row.cluster}
	region_by_cluster = (
		dict(frappe.get_all("Atlas Instance", filters={"name": ["in", list(clusters)]}, fields=["name", "region"], as_list=True))
		if clusters
		else {}
	)

	resources = [
		{
			"kind": "server",
			"name": a.name,
			"label": a.title or a.resource_id,
			"status": a.status,
			"region": region_by_cluster.get(a.cluster),
			"detail": a.public_ipv4,
		}
		for a in servers
	] + [
		{"kind": "site", "name": s.name, "label": s.name, "status": s.status, "region": s.region, "detail": s.url}
		for s in sites
	]

	return {"team": team, "resources": resources}


@frappe.whitelist(methods=["GET"])
def list_site_groups(team: str | None = None) -> dict:
	"""A team's sites grouped by region with an exact per-region count, for the
	servers map + panel. The DB does the grouping, counting and per-region capping
	(indexed on team, region), so the payload never scales with a team's site count."""
	user = frappe.session.user
	team = resolve_team(user, team)
	if not can(user, team, "server:view"):
		frappe.throw(_("You can't view this team's resources."), frappe.PermissionError)

	# ROW_NUMBER caps each region to a preview; COUNT(*) OVER carries the true total.
	site = DocType("Site")
	ranked = (
		frappe.qb.from_(site)
		.select(
			site.name,
			site.status,
			site.url,
			site.region,
			an.RowNumber().over(site.region).orderby(site.modified, order=Order.desc).as_("rn"),
			an.Count(site.star).over(site.region).as_("region_count"),
		)
		.where((site.team == team) & (site.status != "Terminated"))
	).as_("ranked")
	rows = (
		frappe.qb.from_(ranked)
		.select(ranked.name, ranked.status, ranked.url, ranked.region, ranked.region_count)
		.where(ranked.rn <= SITE_PREVIEW_LIMIT)
		.orderby(ranked.region, ranked.rn)
		.run(as_dict=True)
	)

	groups: dict[str, dict] = {}
	for row in rows:
		group = groups.setdefault(row.region or "", {"region": row.region, "count": row.region_count, "sites": []})
		group["sites"].append({"name": row.name, "status": row.status, "url": row.url})

	return {"team": team, "groups": list(groups.values())}
