from __future__ import annotations

import frappe
from frappe import _

from central.iam import can, resolve_team

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
