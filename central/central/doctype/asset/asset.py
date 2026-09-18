from __future__ import annotations

import frappe
from frappe.model.document import Document
from requests import RequestException


class Asset(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		atlas_image_id: DF.Data | None
		atlas_vm_id: DF.Data | None
		cluster: DF.Link
		disk_gigabytes: DF.Float
		frappe_version: DF.Data | None
		gateway_url: DF.Data | None
		admin_domain_task: DF.Data | None
		image_offering: DF.Link | None
		ipv6_address: DF.Data | None
		memory_megabytes: DF.Int
		plan: DF.Link | None
		public_ipv4: DF.Data | None
		resize_in_progress: DF.Check
		resource_id: DF.Data
		state_observed_at: DF.Datetime | None
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
		notification), so a server turning Failed is not silent in the console."""
		from central.notification import engine

		engine.ensure_event_type(
			"server_failed",
			category="Server",
			severity="Error",
			required_cap="server:view",
			in_app_title="Server failed: {{ reference_name }}",
			in_app_body="Your server {{ reference_name }} entered a Failed state: {{ message }}",
			action_label="View server",
			action_route="/servers",
		)
		engine.dispatch(
			self.team,
			"server_failed",
			message=f"Your server in {self.cluster} entered a Failed state. Review it in the console.",
			reference_doctype="Asset",
			reference_name=self.name,
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

	# Central owns this record. Provisioning opens it, and the fields below are the only
	# ones a region reports back. Identity, title, plan, image and billing links are
	# Central's, and no report may touch them.
	OBSERVED_FIELDS = (
		"status",
		"vcpus",
		"memory_megabytes",
		"disk_gigabytes",
		"ipv6_address",
		"public_ipv4",
		"gateway_url",
	)

	@classmethod
	def record_observed_state(cls, resource_id: str, observed_at, state: dict) -> bool:
		"""Apply what a region reports about a server Central already owns.

		Returns False when there is nothing to apply: an unknown server, or a report
		older than the one already recorded. Only the `OBSERVED_FIELDS` present in
		`state` are written, so a status-only report cannot blank an address."""
		try:
			# Lock first. An unlocked read can miss a report another worker just committed.
			doc = frappe.get_doc("Asset", resource_id, for_update=True)
		except frappe.DoesNotExistError:
			return False
		if doc.is_report_stale(observed_at):
			return False

		for field in cls.OBSERVED_FIELDS:
			if field in state:
				setattr(doc, field, state[field])
		doc.state_observed_at = observed_at
		# The verified region authorizes these values, not the signed-in user.
		doc.save(ignore_permissions=True)
		doc.publish_state_change()
		return True

	@frappe.whitelist(methods=["POST"])
	def sync_state(self) -> dict:
		"""Ask the region what this server is doing now, and record the answer.

		The scheduled reconcile does this on a timer and a region reports changes as they
		happen. This is the operator's way to ask directly when a record looks stale or a
		report was missed."""
		from central.integrations.servers import observe_server

		self.check_permission("read")

		return {"status": observe_server(self)}

	def publish_state_change(self) -> None:
		"""Tell this team's consoles that one of its servers moved.

		The payload is identity only. Every consumer re-reads through the team-scoped
		API, so the socket never becomes a second source of truth for state. The room is
		this server's Team document, and Frappe checks Team read permission before a
		client may join it, so one team's traffic never reaches another's console."""
		frappe.publish_realtime(
			"server_state_changed",
			{"resource_id": self.name},
			doctype="Team",
			docname=self.team,
			after_commit=True,
		)

	def claim_admin_hostname(self) -> None:
		"""Ask Pilot to serve its admin UI at this machine's routed hostname."""
		if self.admin_domain_task or self.status != "Running" or not self.gateway_url:
			return
		if not frappe.db.exists(
			"Pilot Credential", {"asset": self.name, "team": self.team, "status": "Active"}
		):
			return

		from central.integrations.pilot import rename_admin_domain

		try:
			task = rename_admin_domain(self.name, tls=False)
		except RequestException, OSError, ValueError:
			frappe.log_error(
				title=f"Pilot admin domain rename failed: {self.name}",
				message=frappe.get_traceback(with_context=True),
			)
			return

		task_id = task.get("task_id") if isinstance(task, dict) else None
		if task_id:
			self.db_set("admin_domain_task", task_id)
		else:
			frappe.log_error(
				title=f"Pilot admin domain rename returned no task: {self.name}",
				message=frappe.as_json(task),
			)

	def is_report_stale(self, observed_at) -> bool:
		"""True when this server already holds a report newer than `observed_at`."""
		if not observed_at or not self.state_observed_at:
			return False

		return frappe.utils.get_datetime(self.state_observed_at) > frappe.utils.get_datetime(observed_at)

	@staticmethod
	def mark_resizing(resource_id: str, resizing: bool) -> None:
		"""Flag or unflag a server as mid-resize, so the console shows a "Resizing" state
		and gates power actions while the reshape job runs. This is Central's own
		orchestration flag, not an observed field, so a region report never clears it."""
		doc = frappe.get_doc("Asset", resource_id)
		doc.db_set("resize_in_progress", 1 if resizing else 0)
		doc.publish_state_change()

	@staticmethod
	def mark_terminated(resource_id: str, observed_at=None) -> bool:
		"""Record a server as gone, from a delete event or a scoped read that found it
		absent. Termination is final, so no later report can outrank it and there is no
		staleness check to make. Returns False when Central holds no such server."""
		try:
			doc = frappe.get_doc("Asset", resource_id, for_update=True)
		except frappe.DoesNotExistError:
			return False

		doc.status = "Terminated"
		doc.state_observed_at = observed_at or frappe.utils.now_datetime()
		# save(), not db_set(): `on_update` closes the billing segment for a dead server.
		doc.save(ignore_permissions=True)
		doc.publish_state_change()
		return True


def on_doctype_update() -> None:
	frappe.db.add_unique("Asset", ["cluster", "atlas_vm_id"])
	frappe.db.add_index("Asset", ["team", "status"])
