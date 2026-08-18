from __future__ import annotations

import frappe
from frappe.model.document import Document

from central.errors import build_envelope

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

PENDING_STATES = ("Sent", "In Progress")
TERMINAL_STATES = ("Succeeded", "Failed", "Timed Out")


class ResourceAction(Document):
	"""A lifecycle action, opened only once Atlas has accepted the command (status Sent).
	A synchronous rejection never reaches here — it surfaces as an error envelope and leaves
	no row — so every write rides the request's own commit and none of them force one."""

	# begin: auto-generated types
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action: DF.Literal["create", "start", "stop", "terminate", "resize"]
		atlas_task: DF.Data | None
		completed_at: DF.Datetime | None
		correlation_id: DF.Data
		error_code: DF.Data | None
		error_message: DF.SmallText | None
		remediation: DF.SmallText | None
		resource_id: DF.Data | None
		resource_type: DF.Literal["Server", "Site"]
		retriable: DF.Check
		status: DF.Literal["Sent", "In Progress", "Succeeded", "Failed", "Timed Out"]
		team: DF.Link
	# end: auto-generated types

	def before_save(self) -> None:
		"""One owner for the completion stamp: any terminal status carries its timestamp."""
		if self.status in TERMINAL_STATES and not self.completed_at:
			self.completed_at = frappe.utils.now_datetime()

	def on_update(self) -> None:
		"""Nudge the console to re-read after every state change (insert included), so the
		transitional badge flips live over the same list channel the mirror already uses."""
		if not self.resource_id:
			return

		mirror = "Site" if self.resource_type == "Site" else "Asset"
		frappe.publish_realtime(
			"list_update",
			{"doctype": mirror, "name": self.resource_id},
			doctype=mirror,
			after_commit=True,
		)

	# Outcome writes below record what Atlas reported, not what a tenant asked for. They run
	# from the HMAC-verified webhook (as Guest) or the sweep (as Administrator), never from the
	# portal, and a tenant must never be able to rewrite an outcome — so these bypass the
	# doc permission check that the create path (open_action) deliberately honours.

	def _finish_error(self, status: str, envelope: dict) -> None:
		self.status = status
		self.error_code = envelope.get("code")
		self.error_message = envelope.get("message")
		self.remediation = envelope.get("remediation")
		self.retriable = 1 if envelope.get("retriable") else 0
		self.save(ignore_permissions=True)

	def succeed(self) -> None:
		self.status = "Succeeded"
		self.save(ignore_permissions=True)

	@classmethod
	def record_mirror_status(cls, correlation_id: str | None, mirror_status: str | None) -> None:
		"""Transition the action a returning Atlas event confirms, matched by correlation id.
		An unknown or already-finished action is ignored."""
		if not (correlation_id and mirror_status):
			return

		name = frappe.db.get_value("Resource Action", {"correlation_id": correlation_id})
		if not name:
			return

		doc = frappe.get_doc("Resource Action", name)
		if doc.status in TERMINAL_STATES:
			return

		if mirror_status == "Failed":
			doc._finish_error("Failed", build_envelope("ACTION_FAILED", action=doc.action))
		elif mirror_status == SUCCESS_MIRROR_STATUS.get(doc.action):
			doc.succeed()
		elif mirror_status in IN_PROGRESS_MIRROR_STATUS and doc.status != "In Progress":
			doc.status = "In Progress"
			doc.save(ignore_permissions=True)

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
			doc.succeed()
		else:
			doc._finish_error("Timed Out", build_envelope("ACTION_TIMED_OUT", action=doc.action))


def open_action(
	resource_type: str,
	action: str,
	*,
	team: str,
	resource_id: str,
	correlation_id: str,
	status: str = "Sent",
	atlas_task: str | None = None,
) -> ResourceAction:
	"""Open a tracking row once Atlas has accepted the command. `status` is Sent for an
	in-flight action, or Succeeded for one Atlas confirmed synchronously (idempotent
	terminate of an already-gone resource).

	Runs as the acting tenant: the create permission is real (Central User + a server-mutating
	capability on the team, see central/permissions.py), so no permission is bypassed here."""
	return frappe.get_doc(
		{
			"doctype": "Resource Action",
			"resource_type": resource_type,
			"action": action,
			"team": team,
			"resource_id": resource_id,
			"correlation_id": correlation_id,
			"status": status,
			"atlas_task": atlas_task,
		}
	).insert()
