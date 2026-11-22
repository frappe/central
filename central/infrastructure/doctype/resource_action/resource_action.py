import frappe
from frappe import _
from frappe.model.document import Document

from central.billing.catalog.trials import is_trial_plan
from central.central.doctype.activity_event.activity_event import ActivityEvent
from central.errors import AtlasConnectionError, AtlasRequestUncertain, build_envelope, to_error_response
from central.iam import can
from central.infrastructure.doctype.blocked_domain.blocked_domain import BlockedDomain, normalize_domain
from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.infrastructure.doctype.user_mail_account.user_mail_account import UserMailAccount
from central.server_models import ActionStatus, ResizeConfiguration, ServerCreation, SiteCreation
from central.services.doctype.ai_trial_key.ai_trial_key import AITrialKey

PENDING_STATES = ("Queued", "Dispatching", "Sent", "In Progress", "Uncertain")
PENDING_LABEL = {
	"create": "Provisioning",
	"start": "Starting",
	"stop": "Stopping",
	"terminate": "Terminating",
	"restart": "Restarting",
	"resize": "Resizing",
}
# The capability a requester must hold, both when an action is accepted and when it is sent.
ACTION_CAPABILITIES = {
	"create": "server:create",
	"start": "server:power",
	"stop": "server:power",
	"restart": "server:power",
	"terminate": "server:terminate",
	"resize": "server:resize",
}
# The actions a customer runs against an existing server as a plain command.
COMMAND_ACTIONS = ("start", "stop", "restart", "terminate")
# The observed status that means an action reached its goal.
GOAL_STATUS = {
	"create": "Running",
	"start": "Running",
	"stop": "Stopped",
	"restart": "Running",
	"terminate": "Terminated",
}
# A command that has not reached its goal this long after dispatch has timed out.
COMMAND_TIMEOUT_SECONDS = 10 * 60
TERMINAL_STATES = ("Succeeded", "Failed", "Timed Out")
# A creation in one of these states can be sent again while it holds no VM identity.
RETRYABLE_CREATE_STATES = ("Failed", "Timed Out")
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
	return {
		"action": row.name,
		"status": row.status,
		"resource_id": row.resource_id,
		"title": row.title or row.resource_id or row.action,
		"error": get_error(row),
	}


def get_error(row) -> dict | None:
	"""The action's error envelope in the reader's language, from a document or a query row
	with the STATUS_FIELDS. The record keeps only the copy that the catalog cannot rebuild."""
	if not row.error_code:
		return None

	return build_envelope(
		row.error_code,
		action=row.action,
		resource_id=row.resource_id,
		message=row.error_message,
		remediation=row.remediation,
	)


class ResourceAction(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action: DF.Literal["create", "start", "stop", "restart", "terminate", "resize"]
		completed_at: DF.Datetime | None
		correlation_id: DF.Data
		credential: DF.Link | None
		diagnostic: DF.Code | None
		dispatched_at: DF.Datetime | None
		error_code: DF.Data | None
		error_message: DF.SmallText | None
		last_checked_at: DF.Datetime | None
		is_free_trial: DF.Check
		product: DF.Link | None
		region: DF.Link | None
		remediation: DF.SmallText | None
		remote_vm_id: DF.Data | None
		request_digest: DF.Data | None
		request_key: DF.Data | None
		request_payload: DF.JSON | None
		requested_by: DF.Link | None
		reserved_monthly_rate: DF.Currency
		resource_id: DF.Data | None
		resource_type: DF.Literal["Server", "Site"]
		retriable: DF.Check
		server: DF.Link | None
		status: DF.Literal[
			"Queued", "Dispatching", "Sent", "In Progress", "Succeeded", "Failed", "Uncertain", "Timed Out"
		]
		subdomain: DF.Data | None
		take_snapshot: DF.Check
		team: DF.Link
		title: DF.Data | None
		user_data: DF.Password | None
		vm_snapshot: DF.Link | None
	# end: auto-generated types

	"""One durable resource operation, from validated intent to confirmed outcome."""

	def before_insert(self) -> None:
		self.requested_by = self.requested_by or frappe.session.user
		self.correlation_id = self.correlation_id or frappe.generate_hash(length=32)
		self.resource_id = self.resource_id or self.server

	def after_insert(self) -> None:
		if self.status == "Queued":
			self.enqueue()

		if self.is_trial_creation:
			first_touch = frappe.db.get_value(
				"Team",
				self.team,
				["utm_source", "utm_medium", "utm_campaign", "referrer", "landing_product"],
				as_dict=True,
			)
			self.capture_trial_event("trial_requested", region=self.region, **first_touch)

	def before_validate(self) -> None:
		"""Keep the user data out of the request a customer can read. It can hold the passwords
		a customer typed for an app, so it goes to the encrypted `user_data` field."""
		payload = frappe.parse_json(self.request_payload or "{}")
		if not isinstance(payload, dict) or "user_data" not in payload:
			return

		if user_data := payload.pop("user_data"):
			self.user_data = user_data
		self.request_payload = payload

	def validate(self) -> None:
		self.validate_subdomain()
		self.validate_status_change()

	def validate_subdomain(self) -> None:
		if not self.subdomain:
			return

		if self.has_value_changed("subdomain") or self.has_value_changed("region"):
			self.subdomain = normalize_domain(self.subdomain)
			zone = frappe.get_cached_value("Region", self.region, "proxy_domain")
			BlockedDomain.validate_assignment(f"{self.subdomain}.{zone}")

	def validate_status_change(self) -> None:
		"""A finished action stays finished. Only a retry sends a failed creation again."""
		previous = self.get_doc_before_save()
		if not previous or previous.status not in TERMINAL_STATES or previous.status == self.status:
			return

		is_retry = self.action == "create" and previous.status in RETRYABLE_CREATE_STATES
		if not (is_retry and self.status == "Queued"):
			frappe.throw(
				_("A {0} action cannot move from {1} to {2}.").format(
					self.action, previous.status, self.status
				)
			)

	def before_save(self) -> None:
		if not self.has_value_changed("status"):
			return

		now = frappe.utils.now_datetime()
		self.completed_at = now if self.status in TERMINAL_STATES else None
		if self.status == "Dispatching":
			self.dispatched_at = now
		elif self.status == "Queued":
			self.dispatched_at = None

	def on_update(self) -> None:
		if not self.has_value_changed("status"):
			return

		self.publish_status_change()
		if self.status in TERMINAL_STATES:
			ActivityEvent.record_action(self)

		if self.status == "Succeeded":
			self.handle_success()
		elif self.status in ("Failed", "Timed Out"):
			self.handle_failure()

	def handle_success(self) -> None:
		"""A trial that moves to a paid plan with storage gets its bundled bucket."""
		from central.integrations.pilot import plan_includes_storage

		if not self.is_trial_upgrade() or not plan_includes_storage(self.get_resize_configuration().plan):
			return

		frappe.enqueue(
			"central.integrations.pilot.attach_bundled_bucket",
			server=self.server,
			queue="long",
			enqueue_after_commit=True,
			job_id=f"bundled-bucket:{self.server}",
			deduplicate=True,
		)

	def handle_failure(self) -> None:
		"""Release a failed creation's reservations and tell the team once."""
		if self.action == "create":
			self.release_creation_resources()

		self.queue_attention_notification()
		if self.is_trial_creation:
			self.capture_trial_event("trial_failed", status=self.status, error_code=self.error_code)

	def release_creation_resources(self) -> None:
		"""Release what a failed creation reserved. No server will link the mailbox, trial key or
		bucket, so termination would not release them."""
		# A creation the region never accepted leaves no machine to use its credential.
		if not self.remote_vm_id:
			PilotCredential.revoke_by_id(self.credential)

		UserMailAccount.queue_removal(resource_action=self.name, server=("is", "not set"))
		AITrialKey.queue_revoke(resource_action=self.name, server=("is", "not set"))
		if not self.server:
			frappe.enqueue(
				"central.integrations.pilot.delete_bundled_bucket",
				action=self.name,
				enqueue_after_commit=True,
			)

	def publish_status_change(self) -> None:
		"""Tell the team's consoles that an action moved, so a pending label changes without
		waiting for the next poll. The payload is identity only, like a server state change."""
		frappe.publish_realtime(
			"server_state_changed",
			{"resource_id": self.resource_id},
			doctype="Team",
			docname=self.team,
			after_commit=True,
		)

	def is_allowed(self) -> bool:
		"""Whether the requester still holds the capabilities this action needs."""
		server = self.server or None
		if not can(self.requested_by, self.team, ACTION_CAPABILITIES[self.action], server=server):
			return False

		return not self.take_snapshot or can(self.requested_by, self.team, "server:snapshot", server=server)

	def enqueue(self) -> None:
		from central.integrations.resource_actions import get_job_timeout_seconds

		frappe.enqueue(
			"central.integrations.resource_actions.process_request",
			name=self.name,
			queue="long",
			timeout=get_job_timeout_seconds(self.action),
			enqueue_after_commit=True,
			job_id=f"resource-action:{self.name}",
			deduplicate=True,
		)

	def get_configuration(self) -> ServerCreation:
		payload = frappe.parse_json(self.request_payload)
		if user_data := self.get_password("user_data", raise_exception=False):
			payload["user_data"] = user_data
		return ServerCreation.model_validate(payload)

	def get_site_creation(self) -> SiteCreation | None:
		"""The trial site part of a creation request. Older requests carry none."""
		site = (frappe.parse_json(self.request_payload or "{}") or {}).get("site")
		return SiteCreation.model_validate(site) if site else None

	def get_resize_configuration(self) -> ResizeConfiguration:
		return ResizeConfiguration.model_validate(frappe.parse_json(self.request_payload))

	def customer_status(self) -> ActionStatus:
		return action_status(self)

	def set_status(
		self,
		status: str,
		*,
		envelope: dict | None = None,
		diagnostic: str | None = None,
		diagnostic_title: str = "Resource action failed",
		**values,
	) -> None:
		"""Record one action state with its error, and keep operator diagnostics on the record.
		Each call is a check, so it moves `last_checked_at` even when the status stays."""
		self.update(
			{
				"status": status,
				"last_checked_at": frappe.utils.now_datetime(),
				"error_code": envelope["code"] if envelope else None,
				"retriable": int(envelope["retriable"]) if envelope else 0,
				**self.get_custom_copy(envelope),
				**values,
			}
		)
		if diagnostic:
			self.diagnostic = self.get_diagnostic(diagnostic, diagnostic_title)

		self.save_as_system()

	def bind_server(self, server: str) -> None:
		"""Link the Virtual Machine that the region built for this creation."""
		self.server = server
		self.resource_id = server
		self.save_as_system()

	def save_as_system(self) -> None:
		"""Save a write that only Central makes. Its links were checked at insert, and the record
		one points to can be gone by the time the region answers, which must not block the outcome."""
		self.flags.ignore_links = True
		# Only Central writes an action after insert; customers hold read access to it.
		self.save(ignore_permissions=True)

	def fail(self, error: Exception, title: str) -> None:
		"""Record a failed dispatch. An uncertain Atlas reply stays pending for recovery."""
		self.set_status(
			"Uncertain" if isinstance(error, AtlasRequestUncertain) else "Failed",
			envelope=to_error_response(error),
			diagnostic=frappe.get_traceback() if isinstance(error, AtlasConnectionError) else None,
			diagnostic_title=title,
		)

	def settle(self, observed_status: str) -> None:
		"""Settle this action against the server status the region reported."""
		self.reload()
		if self.status in TERMINAL_STATES or self.record_observed_status(observed_status):
			return

		if observed_status in ("Failed", "Terminated"):
			self.set_status("Failed", envelope=build_envelope("ACTION_FAILED", action=self.action))
		elif self.action != "create" and self.is_overdue:
			self.set_status("Timed Out", envelope=build_envelope("ACTION_TIMED_OUT", action=self.action))
		else:
			self.set_status("In Progress")

	def record_observed_status(self, status: str) -> bool:
		"""Move this action on from the state the region reports, and return True when it
		reached its goal. Any other state leaves the action pending: the scoped read
		decides what a surprising state means."""
		if self.action == "resize" or status != GOAL_STATUS[self.action]:
			return False

		self.set_status("Succeeded")

		return True

	@property
	def server_id(self) -> str:
		"""The Virtual Machine this action works on, or the one a creation gives its server."""
		return self.server or f"server-{self.name}"

	@property
	def is_overdue(self) -> bool:
		started = self.dispatched_at or self.creation
		return (
			frappe.utils.time_diff_in_seconds(frappe.utils.now_datetime(), started) > COMMAND_TIMEOUT_SECONDS
		)

	@property
	def is_trial_creation(self) -> bool:
		return self.action == "create" and self.resource_type == "Site"

	def is_trial_upgrade(self) -> bool:
		"""Whether this resize moves a server from a trial plan to a paid plan."""
		if self.action != "resize":
			return False

		configuration = self.get_resize_configuration()
		return is_trial_plan(configuration.from_plan) and not is_trial_plan(configuration.plan)

	def capture_trial_event(self, event: str, **properties) -> None:
		"""Send this trial's step to the signup funnel, once per action."""
		from central.signups.funnel import capture_trial_event

		site = self.get_site_creation()
		capture_trial_event(
			event, self.team, site.product if site else None, user=self.requested_by, **properties
		)

	def get_custom_copy(self, envelope: dict | None) -> dict:
		"""The envelope's message and remediation when they differ from the catalog copy. The
		catalog copy is left out, so each reader gets it in their own language."""
		if not envelope:
			return {"error_message": None, "remediation": None}

		catalog = build_envelope(envelope["code"], action=self.action, resource_id=self.resource_id)
		return {
			"error_message": envelope["message"] if envelope["message"] != catalog["message"] else None,
			"remediation": envelope["remediation"]
			if envelope["remediation"] != catalog["remediation"]
			else None,
		}

	def queue_attention_notification(self) -> None:
		"""Notify once when an action reaches a terminal state that needs attention."""
		from central.notification.engine import queue_event

		event_type = {
			"create": "provision_failure",
			"resize": "resize_failed",
		}.get(self.action, "server_action_required")
		# Catalog copy goes as its code, so each reader gets the sentence in their own language.
		queue_event(
			self.team,
			event_type,
			message=self.error_message if self.error_code else _("The operation did not finish."),
			context={
				"action": self.action,
				"title": self.title or self.resource_id or self.name,
				"error_code": self.error_code,
				"resource_id": self.resource_id,
			},
			reference_doctype=self.doctype,
			reference_name=self.name,
		)

	def record_diagnostic(self, detail: str, title: str = "Resource action diagnostic") -> None:
		"""Keep Atlas detail or a local traceback where a Desk operator investigates it."""
		self.db_set("diagnostic", self.get_diagnostic(detail, title), notify=True)

	def get_diagnostic(self, detail: str, title: str) -> str:
		"""Write the detail to the Error Log and return it as the record's diagnostic text."""
		self.log_error(title=title, message=detail)
		return f"{title}\n\n{detail}"

	@frappe.whitelist(methods=["POST"])
	def check_status(self) -> None:
		self.check_permission("read")
		if self.status in TERMINAL_STATES:
			return

		self.enqueue()

	def onload(self) -> None:
		# The form shows the error in the operator's language, also when only the code is stored.
		self.set_onload("error", get_error(self))

	@frappe.whitelist(methods=["GET"])
	def get_setup_timeline(self) -> list[dict]:
		"""Each step a new site takes, with when it happened, so an operator sees where a signup
		stopped. The page a customer waits on reads the same records."""
		self.check_permission("read")
		site = frappe._dict()
		if self.server:
			fields = ["creation", "ready_at", "claimed_at", "renamed_at", "rename_error"]
			site = frappe.db.get_value("Site", {"server": self.server}, fields, as_dict=True) or site
		failed = self.status in ("Failed", "Timed Out")

		return [
			{"label": _("Requested"), "at": self.creation},
			{"label": _("Sent to region"), "at": self.dispatched_at},
			{
				"label": _("Server created"),
				"at": self.completed_at if self.status == "Succeeded" else None,
				"error": ((get_error(self) or {}).get("message") or self.status) if failed else None,
			},
			{"label": _("Site addressable"), "at": site.creation},
			{"label": _("Site answered"), "at": site.ready_at},
			{"label": _("Signed in"), "at": site.claimed_at},
			{"label": _("Name applied"), "at": site.renamed_at, "error": site.rename_error},
		]

	@frappe.whitelist(methods=["POST"])
	def retry(self) -> ActionStatus:
		"""Send this creation again on the same record, with the same request key, configuration
		and quote. Refused once the region answered with a machine, because a second dispatch would
		build a second server."""
		self.check_permission("read")
		if self.action != "create":
			frappe.throw(_("Only a server creation can be retried. Run this action again from the server."))
		if not can(frappe.session.user, self.team, "server:create"):
			frappe.throw(_("You cannot create servers for this Team."), frappe.PermissionError)
		if self.status not in RETRYABLE_CREATE_STATES:
			frappe.throw(_("Only a failed creation can be retried."))
		if self.remote_vm_id:
			frappe.throw(
				_("The region already accepted a machine for this request. Central will not send it again.")
			)
		# A record from before the saved configuration has nothing to send again.
		if not self.request_payload:
			frappe.throw(_("This request holds no saved configuration. Create the server again."))

		self.revalidate_purchase()
		self.set_status("Queued")
		self.enqueue()

		return self.customer_status()

	def revalidate_purchase(self) -> None:
		"""Check the saved configuration against today's catalog and budget before a retry.
		The reserved rate stays as accepted; headroom, plan eligibility and trial limits are checked again."""
		from central.resource_actions import validate_purchase

		frappe.db.get_value("Team", self.team, "name", for_update=True)
		configuration = self.get_configuration()
		validate_purchase(
			self.team,
			self.region,
			configuration.plan,
			[row.model_dump() for row in configuration.includes],
			configuration.sub_category,
			is_free_trial=bool(self.is_free_trial),
			offering=configuration.offering,
		)


def get_open_creations(team: str) -> list[dict]:
	"""The team's unfinished creations. A creation has no server record until the region
	accepts it, so this is how a console finds its own request."""
	rows = frappe.get_list(
		"Resource Action",
		filters={"team": team, "action": "create", "status": ["in", PENDING_STATES]},
		fields=[*STATUS_FIELDS, "requested_by"],
		order_by="creation asc",
		limit=0,
	)
	return [{**action_status(row), "requested_by": row.requested_by} for row in rows]


def get_pending_labels(team: str) -> dict[str, str]:
	"""The label of each of the team's servers that has an action in flight."""
	rows = frappe.get_list(
		"Resource Action",
		filters={"team": team, "status": ["in", PENDING_STATES], "resource_id": ["is", "set"]},
		fields=["resource_id", "action"],
		order_by="creation asc",
		limit=0,
	)
	return {row.resource_id: PENDING_LABEL[row.action] for row in rows}


def get_creators(team: str) -> dict[str, dict]:
	"""Who asked for each of the team's servers, by server name. A discovered server has none."""
	action = frappe.qb.DocType("Resource Action")
	user = frappe.qb.DocType("User")
	# User is not readable by team members; the team filter scopes this read.
	rows = (
		frappe.qb.from_(action)
		.left_join(user)
		.on(user.name == action.requested_by)
		.select(action.server, action.requested_by, user.full_name)
		.where((action.team == team) & (action.action == "create") & action.server.isnotnull())
		.run(as_dict=True)
	)
	return {row.server: {"created_by": row.requested_by, "created_by_name": row.full_name} for row in rows}


def on_doctype_update() -> None:
	frappe.db.add_unique("Resource Action", ["team", "request_key"])
	frappe.db.add_index("Resource Action", ["team", "status"])
	frappe.db.add_index("Resource Action", ["team", "requested_by", "product", "creation"])
	frappe.db.add_index("Resource Action", ["resource_id", "status"])
	frappe.db.add_index("Resource Action", ["status", "modified"])
	frappe.db.add_index("Resource Action", ["status", "completed_at"])
	frappe.db.add_index("Resource Action", ["server", "action"])
