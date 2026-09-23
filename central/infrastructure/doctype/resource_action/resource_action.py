from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from central.errors import build_envelope
from central.iam import can
from central.server_models import ActionStatus, ServerCreation

PENDING_STATES = ("Queued", "Dispatching", "Sent", "In Progress", "Uncertain")
PENDING_LABEL = {
	"create": "Provisioning",
	"start": "Starting",
	"stop": "Stopping",
	"terminate": "Terminating",
	"restart": "Restarting",
	"resize": "Resizing",
}
ACTION_CAPABILITIES = {
	"start": "server:power",
	"stop": "server:power",
	"restart": "server:power",
	"terminate": "server:terminate",
}
# The observed status that means an action reached its goal.
GOAL_STATUS = {
	"create": "Running",
	"start": "Running",
	"stop": "Stopped",
	"restart": "Running",
	"terminate": "Terminated",
}
# A restart begins and ends at Running, so arriving at Running proves nothing on its own.
# The region publishes no restart counter, so the action waits until it reports the server
# away from the goal once. That report is what shows the restart really began.
ROUND_TRIP_ACTIONS = ("restart",)
TERMINAL_STATES = ("Succeeded", "Failed", "Timed Out")
# What `action_status` reads, so a list query can build the same shape as a document.
STATUS_FIELDS = (
	"name",
	"action",
	"status",
	"resource_id",
	"title",
	"error_code",
	"error_message",
	"remediation",
)


def action_status(row) -> ActionStatus:
	"""The one shape a console reads an action in, built from a document or a query row."""
	error = None
	if row.error_code:
		error = build_envelope(
			row.error_code, action=row.action, message=row.error_message, remediation=row.remediation
		)

	return {
		"action": row.name,
		"status": row.status,
		"resource_id": row.resource_id,
		"title": row.title or row.resource_id or row.action,
		"error": error,
	}


class ResourceAction(Document):
	"""One durable resource operation, from validated intent to confirmed outcome."""

	def after_insert(self) -> None:
		# A site is one call out and one read back, with its customer waiting on the answer,
		# so it is driven inside their request instead of behind a queue.
		if self.status == "Queued" and self.resource_type != "Site":
			self.enqueue()

	def enqueue(self) -> None:
		frappe.enqueue(
			"central.integrations.server_provisioning.process_request",
			name=self.name,
			queue="long",
			enqueue_after_commit=True,
			job_id=f"resource-action:{self.name}",
			deduplicate=True,
		)

	def get_configuration(self) -> ServerCreation:
		return ServerCreation.model_validate(frappe.parse_json(self.request_payload))

	def customer_status(self) -> ActionStatus:
		return action_status(self)

	def set_error(self, status: str, envelope: dict) -> None:
		self.db_set(
			{
				"status": status,
				"error_code": envelope["code"],
				"error_message": envelope["message"],
				"remediation": envelope["remediation"],
				"retriable": int(envelope["retriable"]),
				"last_checked_at": frappe.utils.now_datetime(),
				"completed_at": frappe.utils.now_datetime() if status in TERMINAL_STATES else None,
			},
			notify=True,
		)

	def succeed(self) -> None:
		self.db_set(
			{
				"status": "Succeeded",
				"completed_at": frappe.utils.now_datetime(),
				"error_code": None,
				"error_message": None,
				"remediation": None,
				"retriable": 0,
			},
			notify=True,
		)

	@classmethod
	def confirm_observed_status(cls, resource_id: str, status: str) -> None:
		"""Advance the action waiting on this server against what the region reports."""
		waiting = frappe.db.get_value(
			"Resource Action",
			{"resource_id": resource_id, "status": ["in", PENDING_STATES]},
			"name",
			order_by="creation asc",
		)
		if waiting:
			frappe.get_doc("Resource Action", waiting).record_observed_status(status)

	def record_observed_status(self, status: str) -> bool:
		"""Move this action on from the state the region reports, and return True when it
		reached its goal. Any other state leaves the action pending: the scoped read
		decides what a surprising state means."""
		goal = GOAL_STATUS[self.action]
		if self.action in ROUND_TRIP_ACTIONS and self.status != "In Progress":
			if status != goal:
				self.db_set({"status": "In Progress", "last_checked_at": frappe.utils.now_datetime()})
			return False

		if status != goal:
			return False

		self.succeed()
		return True

	@frappe.whitelist(methods=["POST"])
	def check_status(self) -> None:
		self.check_permission("read")
		if self.status in TERMINAL_STATES:
			return

		self.enqueue()

	@frappe.whitelist(methods=["POST"])
	def retry(self) -> ActionStatus:
		"""Send this creation again, on the record that already holds its validated intent.

		A retry never opens a second record, so the request key, the saved configuration
		and the accepted quote all stay the same. It is refused once the region has
		answered with a machine: that identity is the receipt, and a second dispatch would
		build a second server. Other actions are repeated from the server itself, which
		opens a fresh record."""
		self.check_permission("read")
		if self.action != "create":
			frappe.throw(_("Only a server creation can be retried. Run this action again from the server."))
		if not can(frappe.session.user, self.team, "server:create"):
			frappe.throw(_("You cannot create servers for this Team."), frappe.PermissionError)
		if self.status not in ("Failed", "Timed Out"):
			frappe.throw(_("Only a failed creation can be retried."))
		if self.remote_vm_id:
			frappe.throw(
				_("The region already accepted a machine for this request. Central will not send it again.")
			)
		# A record from before the saved configuration has nothing to send again.
		if not self.request_payload:
			frappe.throw(_("This request holds no saved configuration. Create the server again."))

		self.revalidate_purchase()
		self.db_set(
			{
				"status": "Queued",
				"dispatched_at": None,
				"completed_at": None,
				"error_code": None,
				"error_message": None,
				"remediation": None,
				"retriable": 0,
			},
			notify=True,
		)
		self.enqueue()
		return self.customer_status()

	def revalidate_purchase(self) -> None:
		"""Check the saved configuration against today's catalog and budget.

		A failed request holds no budget, so a retry is a new decision to spend. The
		reserved rate stays as it was accepted; only the team's remaining headroom, plan
		eligibility and trial limits are checked again."""
		from central.server_provisioning import validate_purchase

		configuration = self.get_configuration()
		validate_purchase(
			self.team,
			self.atlas_instance,
			configuration.plan,
			[row.model_dump() for row in configuration.includes],
			configuration.sub_category,
		)

	@classmethod
	def open_creations(cls, team: str) -> list[dict]:
		"""The team's creations that have not finished yet.

		A creation has no server record until the region accepts it, so there is no row
		for `pending_labels` to mark and no other way for a console to find a request it
		started. `requested_by` lets a console pick up its own request without adopting a
		teammate's."""
		rows = frappe.get_list(
			"Resource Action",
			filters={"team": team, "action": "create", "status": ["in", PENDING_STATES]},
			fields=[*STATUS_FIELDS, "requested_by"],
			order_by="creation asc",
			limit=0,
		)
		return [{**action_status(row), "requested_by": row.requested_by} for row in rows]

	@classmethod
	def pending_labels(cls, team: str) -> dict[str, str]:
		rows = frappe.get_list(
			"Resource Action",
			filters={"team": team, "status": ["in", PENDING_STATES], "resource_id": ["is", "set"]},
			fields=["resource_id", "action"],
			order_by="creation asc",
			limit=0,
		)
		return {row.resource_id: PENDING_LABEL[row.action] for row in rows}


def on_doctype_update() -> None:
	frappe.db.add_unique("Resource Action", ["team", "request_key"])
	frappe.db.add_index("Resource Action", ["team", "status"])
	frappe.db.add_index("Resource Action", ["status", "modified"])
	frappe.db.add_index("Resource Action", ["atlas_instance", "remote_vm_id"])
