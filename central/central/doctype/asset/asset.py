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
