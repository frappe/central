from __future__ import annotations

import frappe
from frappe.model.document import Document

from central.errors import build_envelope, to_error_response

# Which mirror status means "this action reached its goal". Servers and sites share the
# same status vocabulary, so one map covers both.
SUCCESS_MIRROR_STATUS = {
	"create": "Running",
	"start": "Running",
	"stop": "Stopped",
	"terminate": "Terminated",
}

# Mirror statuses that mean the action is still working, not yet done or failed.
IN_PROGRESS_MIRROR_STATUS = {"Pending", "Provisioning", "Deploying"}

# The transitional label the console shows while an action is in flight.
PENDING_LABEL = {
	"create": "Provisioning",
	"start": "Starting",
	"stop": "Stopping",
	"terminate": "Terminating",
	"resize": "Resizing",
}

PENDING_STATES = ("Queued", "Sent", "In Progress")
TERMINAL_STATES = ("Succeeded", "Failed", "Timed Out")


class ResourceAction(Document):
	# begin: auto-generated types
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action: DF.Literal["create", "start", "stop", "terminate", "resize"]
		atlas_task: DF.Data | None
		completed_at: DF.Datetime | None
		error_code: DF.Data | None
		error_message: DF.SmallText | None
		remediation: DF.SmallText | None
		resource_id: DF.Data | None
		resource_type: DF.Literal["Server", "Site"]
		retriable: DF.Check
		status: DF.Literal["Queued", "Sent", "In Progress", "Succeeded", "Failed", "Timed Out"]
		team: DF.Link
	# end: auto-generated types

	def attach_resource(self, resource_id: str) -> None:
		"""Bind the id a create only learns after Atlas replies, then mark it sent."""
		self.resource_id = resource_id
		self.mark_sent()

	def mark_sent(self, atlas_task: str | None = None) -> None:
		"""Atlas accepted the command; the action is now in flight pending its outcome."""
		if self.status in TERMINAL_STATES:
			return

		self.status = "Sent"
		if atlas_task:
			self.atlas_task = atlas_task
		self._apply()

	def fail_from_exception(self, exc: Exception) -> None:
		"""Record a synchronous failure from the envelope the exception already carries."""
		self._finish_error("Failed", to_error_response(exc))

	def _finish_error(self, status: str, envelope: dict) -> None:
		self.status = status
		self.error_code = envelope.get("code")
		self.error_message = envelope.get("message")
		self.remediation = envelope.get("remediation")
		self.retriable = 1 if envelope.get("retriable") else 0
		self.completed_at = frappe.utils.now_datetime()
		# Commit before any caller re-raises: the request rolls back on the way out, which
		# would otherwise discard the outcome and leave the action stuck in flight.
		self._apply(commit=True)

	def _succeed(self) -> None:
		self.status = "Succeeded"
		self.completed_at = frappe.utils.now_datetime()
		self._apply()

	@classmethod
	def record_mirror_status(cls, correlation_id: str | None, mirror_status: str | None) -> None:
		"""Transition the action a returning Atlas event confirms. The event's correlation id
		is this row's name; an unknown or already-finished action is ignored."""
		if not (correlation_id and mirror_status):
			return
		if not frappe.db.exists("Resource Action", correlation_id):
			return

		doc = frappe.get_doc("Resource Action", correlation_id)
		if doc.status in TERMINAL_STATES:
			return

		if mirror_status == "Failed":
			doc._finish_error("Failed", build_envelope("ACTION_FAILED", action=doc.action))
		elif mirror_status == SUCCESS_MIRROR_STATUS.get(doc.action):
			doc._succeed()
		elif mirror_status in IN_PROGRESS_MIRROR_STATUS and doc.status != "In Progress":
			doc.status = "In Progress"
			doc._apply()

	@classmethod
	def pending_labels(cls, team: str) -> dict[str, str]:
		"""resource_id -> transitional label for the team's in-flight actions, so the console
		shows "Terminating…"/"Provisioning…" from the click until the mirror catches up. A
		VM id and a site FQDN never collide, so one map serves both lists. Latest wins."""
		rows = frappe.get_all(
			"Resource Action",
			filters={"team": team, "status": ["in", PENDING_STATES], "resource_id": ["is", "set"]},
			fields=["resource_id", "action"],
			order_by="creation asc",
		)
		return {row.resource_id: PENDING_LABEL[row.action] for row in rows}

	@classmethod
	def sweep_stale(cls, minutes: int = 15) -> int:
		"""Resolve actions stuck in flight past `minutes`: if the mirror already shows the goal
		(the confirming event was lost but reconcile caught up) mark them Succeeded, otherwise
		Timed Out with a clear message. Keeps a lost event from spinning the UI forever."""
		cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-minutes)
		stuck = frappe.get_all(
			"Resource Action",
			filters={"status": ["in", PENDING_STATES], "creation": ["<", cutoff]},
			pluck="name",
		)
		for name in stuck:
			cls._resolve_stale(frappe.get_doc("Resource Action", name))

		return len(stuck)

	@classmethod
	def _resolve_stale(cls, doc: "ResourceAction") -> None:
		mirror = "Site" if doc.resource_type == "Site" else "Asset"
		goal = SUCCESS_MIRROR_STATUS.get(doc.action)
		reached = doc.resource_id and goal and frappe.db.get_value(mirror, doc.resource_id, "status") == goal
		if reached:
			doc._succeed()
		else:
			doc._finish_error("Timed Out", build_envelope("ACTION_TIMED_OUT", action=doc.action))

	def _apply(self, *, commit: bool = False) -> None:
		self.save(ignore_permissions=True)
		if commit:
			frappe.db.commit()
		self._poke_console()

	def _poke_console(self) -> None:
		"""Nudge the console to re-read once this row commits, so the transitional state flips
		live over the same list channel the mirror already uses — no polling."""
		if not self.resource_id:
			return

		mirror = "Site" if self.resource_type == "Site" else "Asset"
		frappe.publish_realtime(
			"list_update",
			{"doctype": mirror, "name": self.resource_id},
			doctype=mirror,
			after_commit=True,
		)
