from __future__ import annotations

import frappe
from frappe.model.document import Document


class Asset(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		cluster: DF.Link
		disk_gigabytes: DF.Int
		gateway_url: DF.Data | None
		ipv6_address: DF.Data | None
		last_event_at: DF.Datetime | None
		last_synced_at: DF.Datetime | None
		memory_megabytes: DF.Int
		public_ipv4: DF.Data | None
		resource_id: DF.Data
		status: DF.Literal["Pending", "Running", "Paused", "Stopped", "Failed", "Terminated"]
		team: DF.Link
		title: DF.Data | None
		vcpus: DF.Int
	# end: auto-generated types

	# Asset is a read-only mirror of a VM on some Atlas cluster. These methods are
	# the mirror's sole writer, called by the integration layer
	# (central.integrations.atlas) from both the event push and the reconcile pull.
	# Source of truth stays in Atlas.

	@staticmethod
	def is_stale(resource_id: str, occurred_at) -> bool:
		"""Last-writer-wins: True if a newer event has already been applied."""
		last = frappe.db.get_value("Asset", resource_id, "last_event_at")
		return bool(last and occurred_at and frappe.utils.get_datetime(last) > frappe.utils.get_datetime(occurred_at))

	@classmethod
	def mirror_vm(cls, cluster: str, vm: dict, *, occurred_at=None, synced_at=None) -> None:
		"""Upsert one VM into the mirror. `occurred_at` (event push) drives LWW;
		`synced_at` (reconcile pull) just stamps freshness. A VM with no team
		(`central_reference`) belongs to no mirror and is skipped."""
		resource_id, team = vm.get("name"), vm.get("central_reference")
		if not resource_id or not team or not frappe.db.exists("Team", team):
			return
		exists = frappe.db.exists("Asset", resource_id)
		if exists and occurred_at and cls.is_stale(resource_id, occurred_at):
			return
		doc = frappe.get_doc("Asset", resource_id) if exists else frappe.new_doc("Asset")
		doc.resource_id = resource_id
		doc.team = team
		doc.cluster = cluster
		doc.status = vm.get("status") or "Pending"
		doc.title = vm.get("title")
		doc.vcpus = vm.get("vcpus")
		doc.memory_megabytes = vm.get("memory_megabytes")
		doc.disk_gigabytes = vm.get("disk_gigabytes")
		doc.ipv6_address = vm.get("ipv6_address")
		doc.public_ipv4 = vm.get("public_ipv4")
		doc.gateway_url = vm.get("gateway_url") or None
		if occurred_at:
			doc.last_event_at = occurred_at
		if synced_at:
			doc.last_synced_at = synced_at
		# Users can't write the mirror; this sync is its sole writer, authorized by
		# the verified Atlas event/pull rather than desk RBAC.
		doc.save(ignore_permissions=True)

	@staticmethod
	def mark_terminated(resource_id: str, *, last_event_at=None, last_synced_at=None) -> None:
		"""Flag a VM that's gone (delete event, or vanished on reconcile) Terminated."""
		stamp = {"status": "Terminated"}
		if last_event_at:
			stamp["last_event_at"] = last_event_at
		if last_synced_at:
			stamp["last_synced_at"] = last_synced_at
		frappe.db.set_value("Asset", resource_id, stamp)
