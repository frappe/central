from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from requests import RequestException


class VirtualMachine(Document):
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
		admin_domain_error: DF.SmallText | None
		admin_domain_error_log: DF.Link | None
		image_offering: DF.Link | None
		ipv6_address: DF.Data | None
		last_reported_at: DF.Datetime | None
		memory_megabytes: DF.Int
		plan: DF.Link | None
		public_ipv4: DF.Data | None
		resource_id: DF.Data
		skip_automatic_snapshot: DF.Check
		state_observed_at: DF.Datetime | None
		status: DF.Literal[
			"Pending", "Provisioning", "Deploying", "Running", "Paused", "Stopped", "Failed", "Terminated"
		]
		team: DF.Link
		title: DF.Data | None
		vcpus: DF.Int
	# end: auto-generated types

	@classmethod
	def create_from_action(cls, action, resource_id: str) -> VirtualMachine:
		"""Create Central's server record from one accepted creation action."""
		if frappe.db.exists("Virtual Machine", resource_id):
			return frappe.get_doc("Virtual Machine", resource_id)

		configuration = action.get_configuration()
		server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": resource_id,
				"title": action.title,
				"team": action.team,
				"cluster": action.atlas_instance,
				"status": "Provisioning",
				"atlas_vm_id": action.remote_vm_id,
				"atlas_image_id": configuration.image_id,
				"image_offering": configuration.offering,
				"plan": configuration.plan,
				"vcpus": configuration.virtual_cpu_count,
				"memory_megabytes": configuration.memory_mib,
				"disk_gigabytes": configuration.disk_mib / 1024,
				"frappe_version": configuration.image_tags.get("frappe_version"),
			}
		)
		# The authorized Resource Action permits this system-owned mirror write.
		return server.insert(ignore_permissions=True)

	def on_update(self):
		if self.has_value_changed("status") or self.has_value_changed("plan"):
			self.sync_subscription_on_status_change()
		if self.has_value_changed("status") and self.status == "Failed":
			self.queue_status_notification("server_failed")
		if self.has_value_changed("status") and self.status == "Terminated":
			self.enqueue_route_removal()
			self.queue_status_notification("server_terminated")

	def enqueue_route_removal(self) -> None:
		"""A terminated server serves nothing, so its site and custom-domain routes go too."""
		frappe.enqueue(
			"central.infrastructure.doctype.site_domain.site_domain.remove_server_routes",
			server=self.name,
			enqueue_after_commit=True,
			job_id=f"server-routes-removal:{self.name}",
			deduplicate=True,
		)

	def queue_status_notification(self, event_type: str) -> None:
		"""Queue a notification after the observed server state is committed."""
		from central.notification.engine import queue_event

		message = None
		if event_type == "server_failed":
			message = _("The region reported a failure for this server.")
		queue_event(
			self.team,
			event_type,
			message=message,
			reference_doctype="Virtual Machine",
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
			"Subscription", {"team": self.team, "server_id": self.name}, "name", order_by="creation desc"
		)
		if existing:
			sub = frappe.get_doc("Subscription", existing)
			if not sub.enabled:
				sub.enable()
			if sub.plan != self.plan:
				sub.plan = self.plan
				# The observed server lifecycle owns its system-managed subscription.
				sub.save(ignore_permissions=True)
		else:
			subscription = frappe.get_doc(
				{
					"doctype": "Subscription",
					"team": self.team,
					"server_id": self.name,
					"plan": self.plan,
					"enabled": 1,
				}
			)
			# The observed server lifecycle owns its system-managed subscription.
			subscription.insert(ignore_permissions=True)

	def disable_active_subscription(self):
		"""Terminated: cancel the team's active subscription for this server, if any.

		Termination is an END, not a billing pause — so we record a `Cancelled`
		Subscription Change to CLOSE the open billing segment (ADR 0010). That drops the
		subscription from the team's run-rate and frees its trust-tier headroom, so the
		bill estimate stops counting a dead VM and the team can provision again. Then we
		disable it (the `enabled: 1` filter makes this idempotent on a repeated event)."""
		existing = frappe.db.get_value(
			"Subscription", {"team": self.team, "server_id": self.name, "enabled": 1}, "name"
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
	def record_observed_state(cls, resource_id: str, observed_at, state: dict, *, reported_at=None) -> bool:
		"""Apply a region's report. `reported_at` is the region's own timestamp for a
		webhook; a report not newer than the last is dropped (reconcile omits it and always
		applies). Returns False when the server is absent or the report is stale."""
		try:
			# Lock first, so a concurrent worker's write is not missed.
			doc = frappe.get_doc("Virtual Machine", resource_id, for_update=True)
		except frappe.DoesNotExistError:
			return False
		if reported_at is not None and not doc.is_newer_report(reported_at):
			return False

		observed = {field: state[field] for field in cls.OBSERVED_FIELDS if field in state}
		changed = any(doc.get(field) != value for field, value in observed.items())
		for field, value in observed.items():
			setattr(doc, field, value)
		doc.state_observed_at = observed_at
		if reported_at is not None:
			doc.last_reported_at = reported_at
		doc.save(ignore_permissions=True)
		if changed:
			doc.publish_state_change()
		return True

	@frappe.whitelist(methods=["POST"])
	def remove_routes(self) -> None:
		"""Operator action: queue the route removal again, for a terminated server whose
		routes outlived a lost or failed job."""
		self.check_permission("write")
		if self.status != "Terminated":
			frappe.throw(frappe._("Only a terminated server's routes can be removed."))

		self.enqueue_route_removal()

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
		# A reserved pilot is Active before enrollment issues its audience; only a fully
		# enrolled pilot (audience set) has an identity to sign the admin-domain call.
		if not frappe.db.exists(
			"Pilot Credential",
			{"server": self.name, "team": self.team, "status": "Active", "audience_id": ["is", "set"]},
		):
			return

		from central.integrations.pilot import rename_admin_domain

		try:
			task = rename_admin_domain(self.name, tls=False)
		except RequestException, OSError, ValueError:
			self.record_admin_domain_failure(
				_("Pilot did not accept the admin hostname change. Central will retry it."),
				"Pilot admin domain rename failed",
				frappe.get_traceback(with_context=False),
			)
			return

		task_id = task.get("task_id") if isinstance(task, dict) else None
		if task_id:
			self.db_set(
				{
					"admin_domain_task": task_id,
					"admin_domain_error": None,
					"admin_domain_error_log": None,
				}
			)
		else:
			self.record_admin_domain_failure(
				_("Pilot did not return a task for the admin hostname change. Central will retry it."),
				"Pilot admin domain rename returned no task",
				frappe.as_json(task),
			)

	def record_admin_domain_failure(self, reason: str, title: str, diagnostic: str) -> None:
		"""Keep the admin-hostname failure beside the server a Desk operator opens."""
		error_log = self.log_error(title=title, message=diagnostic)
		self.db_set(
			{
				"admin_domain_error": reason,
				"admin_domain_error_log": error_log.name,
			}
		)

	def is_newer_report(self, reported_at) -> bool:
		"""True when `reported_at` is newer than the last applied report. A missing
		timestamp, or a first report, is allowed through."""
		if not reported_at or not self.last_reported_at:
			return True

		return frappe.utils.get_datetime(reported_at) > frappe.utils.get_datetime(self.last_reported_at)

	@staticmethod
	def mark_terminated(resource_id: str, observed_at=None) -> bool:
		"""Record a server as gone, from a delete event or a scoped read that found it
		absent. Termination is final, so no later report can outrank it and there is no
		staleness check to make. Returns False when Central holds no such server."""
		try:
			doc = frappe.get_doc("Virtual Machine", resource_id, for_update=True)
		except frappe.DoesNotExistError:
			return False

		doc.status = "Terminated"
		doc.state_observed_at = observed_at or frappe.utils.now_datetime()
		# save(), not db_set(): `on_update` closes the billing segment for a dead server.
		doc.save(ignore_permissions=True)
		doc.publish_state_change()
		return True


def on_doctype_update() -> None:
	frappe.db.add_unique("Virtual Machine", ["cluster", "atlas_vm_id"])
	frappe.db.add_index("Virtual Machine", ["team", "status"])
