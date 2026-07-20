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
		frappe_version: DF.Data | None
		gateway_url: DF.Data | None
		ipv6_address: DF.Data | None
		last_event_at: DF.Datetime | None
		last_synced_at: DF.Datetime | None
		login_url: DF.SmallText | None
		login_url_expires_at: DF.Datetime | None
		memory_megabytes: DF.Int
		plan: DF.Link | None
		public_ipv4: DF.Data | None
		resize_in_progress: DF.Check
		resource_id: DF.Data
		status: DF.Literal[
			"Pending", "Provisioning", "Deploying", "Running", "Paused", "Stopped", "Failed", "Terminated"
		]
		team: DF.Link
		title: DF.Data | None
		vcpus: DF.Int
	# end: auto-generated types

	def on_update(self):
		if self.has_value_changed("status") or self.has_value_changed("plan"):
			self.sync_subscription_on_status_change()
		if self.has_value_changed("status") and self.status == "Failed":
			self.notify_failure()

	def notify_failure(self):
		"""Surface a failed server in the team's console feed (a Server-category
		notification), so a mirror flipping to Failed isn't silent in the UI."""
		from central.notification import create_notification

		create_notification(
			self.team,
			f"Server {self.name} failed",
			category="Server",
			event_type="Server Failed",
			severity="Error",
			message=f"Your server in {self.cluster} entered a Failed state. Review it in the console.",
			reference_doctype="Asset",
			reference_name=self.name,
			action_label="View server",
			action_route="/servers",
		)

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
		"""Terminated: cancel the team's active subscription for this asset, if any.

		Termination is an END, not a billing pause — so we record a `Cancelled`
		Subscription Change to CLOSE the open billing segment (ADR 0010). That drops the
		subscription from the team's run-rate and frees its trust-tier headroom, so the
		bill estimate stops counting a dead VM and the team can provision again. Then we
		disable it (the `enabled: 1` filter makes this idempotent on a repeated event)."""
		existing = frappe.db.get_value(
			"Subscription", {"team": self.team, "asset_id": self.name, "enabled": 1}, "name"
		)
		if existing:
			from central.billing.catalog.subscriptions import cancel_subscription

			cancel_subscription(existing)
			frappe.get_doc("Subscription", existing).disable()
	# Asset is a read-only mirror of a VM on some Atlas cluster. These methods are
	# the mirror's sole writer, called by the integration layer
	# (central.integrations.atlas) from both the event push and the reconcile pull.
	# Source of truth stays in Atlas.

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
		# Lock + load in one current read. A plain get_doc after get_value(for_update)
		# still uses the REPEATABLE READ snapshot and can miss a row another writer
		# just committed (DuplicateEntry recovery → DoesNotExistError), or load a
		# stale `modified` (TimestampMismatchError against a concurrent save).
		doc = frappe.get_doc("Asset", resource_id, for_update=True)
		if occurred_at and doc.last_event_at and frappe.utils.get_datetime(doc.last_event_at) > frappe.utils.get_datetime(
			occurred_at
		):
			return
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
		# Provisioned version Atlas echoes; an event that omits it must not wipe it.
		doc.frappe_version = vm.get("frappe_version") or doc.get("frappe_version")
		# Write-once: the bench login URL + its expiry only arrive once the VM is
		# Running (Atlas gates them on status), so never blank a handoff we've already
		# stored on a later status-only event. Same rule as Site's login_url.
		if vm.get("login_url"):
			doc.login_url = vm["login_url"]
			doc.login_url_expires_at = vm.get("login_url_expires_at")
		if occurred_at:
			doc.last_event_at = occurred_at
		if synced_at:
			doc.last_synced_at = synced_at

	@staticmethod
	def mark_resizing(resource_id: str, resizing: bool) -> None:
		"""Flag/unflag a VM as mid-resize so the console shows a "Resizing" state and
		gates power actions while the slow reshape runs in its background job. This is a
		Central-orchestration write (not an Atlas mirror field), so it's independent of
		the status the Atlas events drive. `notify=True` pushes the change to Console
		list subscribers live, without polling."""
		frappe.get_doc("Asset", resource_id).db_set("resize_in_progress", 1 if resizing else 0, notify=True)

	@staticmethod
	def mark_terminated(resource_id: str, *, last_event_at=None, last_synced_at=None) -> None:
		"""Flag a VM that's gone (delete event, or vanished on reconcile) Terminated.

		Locks the row first so LWW sees the committed `last_event_at` — an unlocked
		read under REPEATABLE READ can miss a newer event and wrongly terminate."""
		try:
			doc = frappe.get_doc("Asset", resource_id, for_update=True)
		except frappe.DoesNotExistError:
			return
		if (
			last_event_at
			and doc.last_event_at
			and frappe.utils.get_datetime(doc.last_event_at) > frappe.utils.get_datetime(last_event_at)
		):
			return
		stamp = {"status": "Terminated"}
		if last_event_at:
			stamp["last_event_at"] = last_event_at
		if last_synced_at:
			stamp["last_synced_at"] = last_synced_at
		# db_set(notify=True) emits Frappe's list_update after commit so Console
		# subscribers see terminal state changes without polling.
		doc.db_set(stamp, notify=True)
