from __future__ import annotations

from statistics import median
from typing import TYPE_CHECKING, Literal

import frappe
from frappe.utils.caching import redis_cache

if TYPE_CHECKING:
	from central.infrastructure.doctype.site.site import Site

Phase = Literal["booking", "server", "app", "signing", "failed"]

# What the journey reads from the creation request.
ACTION_FIELDS = ("name", "status", "server", "subdomain", "region", "creation")


class SetupJourney:
	"""Where a new trial site is on its way to the customer, read from the records that own each
	step: the creation request, the machine, and the site's own answer."""

	def __init__(self, action: frappe._dict | None, site: Site | None = None, site_state: dict | None = None):
		self.action = action or frappe._dict()
		self.site = site
		# The poll already read the machine and pinged the site, so the journey reuses that.
		self.site_state = site_state or {}

	def get_phase(self) -> Phase:
		"""The milestone the site is working towards. Signing in is the last one Central sees."""
		server_status = self.site_state.get("status") or (
			self.action.server and frappe.db.get_value("Virtual Machine", self.action.server, "status")
		)
		if self.action.status in ("Failed", "Timed Out") or server_status == "Failed":
			return "failed"
		if self.site_state.get("ready"):
			return "signing"
		if server_status == "Running":
			return "app"
		if self.action.status in ("Queued", "Dispatching"):
			return "booking"
		return "server"

	def as_dict(self) -> dict:
		region = self.action.region or (
			self.site and frappe.db.get_value("Virtual Machine", self.site.server, "region")
		)
		fields = ["display_name", "country_code", "latitude", "longitude", "proxy_domain"]
		details = (
			frappe.get_cached_value("Region", region, fields, as_dict=True) if region else frappe._dict()
		)

		return {
			"phase": self.get_phase(),
			"subdomain": self.action.subdomain or (self.site and self.site.subdomain),
			"domain": details.proxy_domain,
			"region": {
				"title": details.display_name,
				"country_code": details.country_code,
				"latitude": details.latitude,
				"longitude": details.longitude,
			},
			"started_at": self.action.creation,
			"eta_seconds": get_eta_seconds(region) if region else None,
			"reference": self.action.name,
		}


@redis_cache(ttl=600)
def get_eta_seconds(region: str) -> int | None:
	"""The median time from request to a site that answers, over the region's recent trials."""
	action = frappe.qb.DocType("Resource Action")
	site = frappe.qb.DocType("Site")
	rows = (
		frappe.qb.from_(action)
		.join(site)
		.on(site.server == action.server)
		.select(action.creation, site.ready_at)
		.where(
			(action.region == region)
			& (action.resource_type == "Site")
			& (action.action == "create")
			& site.ready_at.isnotnull()
		)
		.orderby(site.ready_at, order=frappe.qb.desc)
		.limit(50)
		.run()
	)
	# A median of a few trials is a guess, so the page shows no estimate.
	if len(rows) < 3:
		return None

	return round(median((ready_at - requested_at).total_seconds() for requested_at, ready_at in rows))
