from __future__ import annotations

import frappe
from frappe.model.document import Document


class Site(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		cluster: DF.Link
		last_event_at: DF.Datetime | None
		last_synced_at: DF.Datetime | None
		login_url: DF.SmallText | None
		login_url_expires_at: DF.Datetime | None
		pilot_credential_id: DF.Data | None
		region: DF.Data | None
		site_name: DF.Data
		status: DF.Literal["Pending", "Provisioning", "Deploying", "Running", "Failed", "Terminated"]
		subdomain: DF.Data | None
		team: DF.Link
		url: DF.Data | None
	# end: auto-generated types

	# Site is a read-only mirror of a self-serve site on some Atlas cluster. These
	# methods are the mirror's sole writer, called by the integration layer
	# (central.integrations.atlas) from the site.* event push. Atlas exposes no
	# tenant_sites reconcile pull, so get_site(name) is the only self-heal — there
	# is no bulk reconcile here. Source of truth stays in Atlas.

	@classmethod
	def mirror_site(cls, cluster: str, site: dict, *, occurred_at=None, synced_at=None) -> None:
		"""Upsert one site into the mirror. `occurred_at` (event push) drives LWW;
		`synced_at` (get_site poll) just stamps freshness. A site with no `team`
		belongs to no mirror and is skipped."""
		from central.mirror import upsert_mirror

		upsert_mirror(
			"Site",
			site.get("name"),
			site.get("team"),
			occurred_at,
			lambda doc: cls._stamp(doc, cluster, site, occurred_at, synced_at),
		)

	@staticmethod
	def _stamp(doc, cluster: str, site: dict, occurred_at, synced_at) -> None:
		doc.site_name = site.get("name")
		doc.team = site.get("team")
		doc.cluster = cluster
		doc.subdomain = site.get("subdomain")
		doc.region = site.get("region")
		doc.status = site.get("status") or "Pending"
		doc.url = site.get("url") or None
		# Write-once: create_site stamps the pilot credential once; later status events
		# omit it and must not blank the binding a site login resolves through.
		if site.get("pilot_credential_id") and not doc.pilot_credential_id:
			doc.pilot_credential_id = site["pilot_credential_id"]
		# Write-once: the one-click login URL + its expiry only arrive once Running
		# (Atlas gates them on status), so never blank a handoff we've already stored on
		# a later (e.g. status-only) event. Same rule as Asset's login_url.
		if site.get("login_url"):
			doc.login_url = site["login_url"]
			doc.login_url_expires_at = site.get("login_url_expires_at")
		if occurred_at:
			doc.last_event_at = occurred_at
		if synced_at:
			doc.last_synced_at = synced_at


def on_doctype_update():
	# Backs the team-scoped, region-grouped read in central.api.resources; runs on migrate.
	frappe.db.add_index("Site", ["team", "region"])
