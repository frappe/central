from __future__ import annotations

import frappe
from frappe.model.document import Document


class Site(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		admin_password: DF.Password | None
		cluster: DF.Link
		last_event_at: DF.Datetime | None
		last_synced_at: DF.Datetime | None
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

	@staticmethod
	def is_stale(site_name: str, occurred_at) -> bool:
		"""Last-writer-wins: True if a newer event has already been applied."""
		last = frappe.db.get_value("Site", site_name, "last_event_at")
		return bool(last and occurred_at and frappe.utils.get_datetime(last) > frappe.utils.get_datetime(occurred_at))

	@classmethod
	def mirror_site(cls, cluster: str, site: dict, *, occurred_at=None, synced_at=None) -> None:
		"""Upsert one site into the mirror. `occurred_at` (event push) drives LWW;
		`synced_at` (get_site poll) just stamps freshness. A site with no `team`
		belongs to no mirror and is skipped."""
		site_name, team = site.get("name"), site.get("team")
		if not site_name or not team or not frappe.db.exists("Team", team):
			return
		if frappe.db.exists("Site", site_name):
			cls._update_mirror(site_name, cluster, site, occurred_at, synced_at)
			return
		try:
			doc = frappe.new_doc("Site")
			cls._stamp(doc, cluster, site, occurred_at, synced_at)
			# Users can't write the mirror; this sync is its sole writer, authorized
			# by the verified Atlas event/poll rather than desk RBAC.
			doc.save(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			# Lost the insert race (concurrent create_site + event): recover as update.
			cls._update_mirror(site_name, cluster, site, occurred_at, synced_at)

	@classmethod
	def _update_mirror(cls, site_name: str, cluster: str, site: dict, occurred_at, synced_at) -> None:
		frappe.db.get_value("Site", site_name, "name", for_update=True)
		if occurred_at and cls.is_stale(site_name, occurred_at):
			return
		doc = frappe.get_doc("Site", site_name)
		cls._stamp(doc, cluster, site, occurred_at, synced_at)
		doc.save(ignore_permissions=True)

	@staticmethod
	def _stamp(doc, cluster: str, site: dict, occurred_at, synced_at) -> None:
		doc.site_name = site.get("name")
		doc.team = site.get("team")
		doc.cluster = cluster
		doc.subdomain = site.get("subdomain")
		doc.region = site.get("region")
		doc.status = site.get("status") or "Pending"
		doc.url = site.get("url") or None
		# Write-once: the handoff password only arrives once Running; never blank a
		# password we've already stored on a later (e.g. status-only) event.
		if site.get("admin_password"):
			doc.admin_password = site["admin_password"]
		if occurred_at:
			doc.last_event_at = occurred_at
		if synced_at:
			doc.last_synced_at = synced_at
