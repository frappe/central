from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from central.errors import build_envelope
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


class ResourceAction(Document):
	"""One durable resource operation, from validated intent to confirmed outcome."""

	def after_insert(self) -> None:
		if self.status == "Queued":
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
		error = None
		if self.error_code:
			error = build_envelope(
				self.error_code, action=self.action, message=self.error_message, remediation=self.remediation
			)

		return {
			"action": self.name,
			"status": self.status,
			"resource_id": self.resource_id,
			"title": self.title or self.resource_id or self.action,
			"error": error,
		}

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
		if self.status == "Uncertain" and not self.remote_vm_id:
			frappe.throw(_("An operator must locate the possible VM before this action can continue."))

		self.enqueue()

	@frappe.whitelist(methods=["POST"])
	def resolve_created_vm(self, remote_vm_id: str) -> None:
		from central.iam import user_has_operator_bypass
		from central.integrations.server_provisioning import resolve_created_vm

		if not user_has_operator_bypass():
			frappe.throw(_("Only an operator can resolve an uncertain create."), frappe.PermissionError)
		self.check_permission("write")
		resolve_created_vm(self.name, remote_vm_id)

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
