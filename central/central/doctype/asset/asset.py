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
		plan: DF.Link | None
		public_ipv4: DF.Data | None
		resource_id: DF.Data
		status: DF.Literal["Pending", "Running", "Paused", "Stopped", "Failed", "Terminated"]
		team: DF.Link
		title: DF.Data | None
		vcpus: DF.Int
	# end: auto-generated types

	def on_update(self):
		if self.has_value_changed("status") or self.has_value_changed("plan"):
			self.sync_subscription_on_status_change()

	def sync_subscription_on_status_change(self):
		"""Provision/enable the subscription on Running; disable it on Terminated."""
		if self.status == "Running":
			self.ensure_subscription_enabled()
		elif self.status == "Terminated":
			self.disable_active_subscription()

	def ensure_subscription_enabled(self):
		"""Create the subscription if missing, else enable it if disabled."""
		existing = frappe.db.get_value(
			"Subscription", {"team": self.team, "asset_id": self.name}, "name", order_by="creation desc"
		)
		if existing:
			sub = frappe.get_doc("Subscription", existing)
			if not sub.enabled:
				sub.enable()
			if sub.plan != self.plan:
				sub.plan = self.plan
				sub.save(ignore_permissions=True)
		else:
			frappe.get_doc(
				{
					"doctype": "Subscription",
					"team": self.team,
					"asset_id": self.name,
					"plan": self.plan,
					"enabled": 1,
				}
			).insert(ignore_permissions=True)

	def disable_active_subscription(self):
		"""Disable the team's active subscription for this asset, if any."""
		existing = frappe.db.get_value(
			"Subscription", {"team": self.team, "asset_id": self.name, "enabled": 1}, "name"
		)
		if existing:
			frappe.get_doc("Subscription", existing).disable()
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
		`synced_at` (reconcile pull) just stamps freshness. A VM with no `team`
		belongs to no mirror and is skipped."""
		resource_id, team = vm.get("name"), vm.get("team")
		if not resource_id or not team or not frappe.db.exists("Team", team):
			return
		if frappe.db.exists("Asset", resource_id):
			cls._update_mirror(resource_id, cluster, vm, occurred_at, synced_at)
			return
		try:
			doc = frappe.new_doc("Asset")
			cls._stamp(doc, cluster, vm, occurred_at, synced_at)
			# Users can't write the mirror; this sync is its sole writer, authorized
			# by the verified Atlas event/pull rather than desk RBAC.
			doc.save(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			# Lost the insert race: under REPEATABLE READ our exists-check ran on a
			# snapshot that predated a concurrent writer's commit, so we took the
			# insert path and hit the unique key. Recover as an update.
			cls._update_mirror(resource_id, cluster, vm, occurred_at, synced_at)

	@classmethod
	def _update_mirror(cls, resource_id: str, cluster: str, vm: dict, occurred_at, synced_at) -> None:
		# A locking read refreshes our snapshot so the row a concurrent insert just
		# committed is visible here, even when we arrive via the lost-race recovery.
		frappe.db.get_value("Asset", resource_id, "name", for_update=True)
		if occurred_at and cls.is_stale(resource_id, occurred_at):
			return
		doc = frappe.get_doc("Asset", resource_id)
		cls._stamp(doc, cluster, vm, occurred_at, synced_at)
		doc.save(ignore_permissions=True)

	@staticmethod
	def _stamp(doc, cluster: str, vm: dict, occurred_at, synced_at) -> None:
		doc.resource_id = vm.get("name")
		doc.team = vm.get("team")
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

	@staticmethod
	def mark_terminated(resource_id: str, *, last_event_at=None, last_synced_at=None) -> None:
		"""Flag a VM that's gone (delete event, or vanished on reconcile) Terminated."""
		stamp = {"status": "Terminated"}
		if last_event_at:
			stamp["last_event_at"] = last_event_at
		if last_synced_at:
			stamp["last_synced_at"] = last_synced_at
		# db_set(notify=True) emits Frappe's list_update after commit so Console
		# subscribers see terminal state changes without polling.
		frappe.get_doc("Asset", resource_id).db_set(stamp, notify=True)
