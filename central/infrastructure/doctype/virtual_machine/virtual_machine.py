import functools
import inspect
from collections.abc import Callable
from typing import TYPE_CHECKING, Self

import frappe
from frappe import _
from frappe.model.document import Document
from requests import RequestException

from central.iam import can, user_has_operator_bypass
from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.infrastructure.doctype.user_mail_account.user_mail_account import UserMailAccount
from central.services.doctype.ai_trial_key.ai_trial_key import AITrialKey
from central.sso import mint_bench_login
from central.utils.units import mebibytes_to_gigabytes, millicores_to_vcpus

if TYPE_CHECKING:
	from central.server_models import FirewallChange


def requires_server_access(method: Callable) -> Callable:
	"""Refuse a server method on an open free trial. A `user` argument names who asks;
	without one, the session user does. Operators keep access."""
	signature = inspect.signature(method)

	@functools.wraps(method)
	def wrapper(self: "VirtualMachine", *args, **kwargs):
		self.require_server_access(signature.bind(self, *args, **kwargs).arguments.get("user"))
		return method(self, *args, **kwargs)

	return wrapper


class VirtualMachine(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from central.infrastructure.doctype.server_ssh_key.server_ssh_key import ServerSSHKey

		admin_domain_diagnostic: DF.Code | None
		admin_domain_error: DF.SmallText | None
		admin_domain_task: DF.Data | None
		atlas_image_id: DF.Data | None
		atlas_host_id: DF.Data | None
		atlas_vm_id: DF.Data | None
		disk_gigabytes: DF.Float
		firewall_rules: DF.JSON | None
		frappe_version: DF.Data | None
		gateway_url: DF.Data | None
		has_ipv4_internet: DF.Check
		has_public_ipv6: DF.Check
		has_site: DF.Check
		image_offering: DF.Link | None
		ipv6_address: DF.Data | None
		is_firewall_enabled: DF.Check
		is_termination_protected: DF.Check
		last_reported_at: DF.Datetime | None
		memory_megabytes: DF.Int
		plan: DF.Link | None
		public_ipv4: DF.Data | None
		public_ipv6: DF.Data | None
		region: DF.Link
		resource_id: DF.Data
		skip_automatic_snapshot: DF.Check
		ssh_keys: DF.Table[ServerSSHKey]
		state_observed_at: DF.Datetime | None
		status: DF.Literal[
			"Pending", "Provisioning", "Deploying", "Running", "Paused", "Stopped", "Failed", "Terminated"
		]
		team: DF.Link
		title: DF.Data | None
		vcpus: DF.Float
	# end: auto-generated types

	@staticmethod
	def get_team_server_name(team: str, resource_id: str | None) -> str:
		"""The server `resource_id` of `team`, or a not-found error."""
		name = frappe.db.get_value("Virtual Machine", {"team": team, "resource_id": resource_id}, "name")
		if not name:
			frappe.throw(
				_(
					"Server '{0}' is not available on this team. Return to Servers and refresh the list."
				).format(resource_id),
				frappe.DoesNotExistError,
			)

		return name

	@classmethod
	def create_from_action(cls, action, resource_id: str) -> Self:
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
				"region": action.region,
				"status": "Provisioning",
				"atlas_vm_id": action.remote_vm_id,
				"atlas_image_id": configuration.image_id,
				"image_offering": configuration.offering,
				"plan": configuration.plan,
				"vcpus": millicores_to_vcpus(configuration.cpu_millicores),
				"memory_megabytes": configuration.memory_mib,
				"disk_gigabytes": mebibytes_to_gigabytes(configuration.disk_mib),
				"frappe_version": configuration.image_tags.get("frappe_version"),
				"has_site": configuration.image_tags.get("has_site") == "1",
				"ssh_keys": [{"team_ssh_key": key} for key in configuration.ssh_key_ids],
				"has_public_ipv6": configuration.has_public_ipv6,
				"is_firewall_enabled": configuration.is_firewall_enabled,
			}
		)

		# The authorized Resource Action permits this system-owned mirror write.
		return server.insert(ignore_permissions=True)

	def validate(self):
		self.title = (self.title or "").strip() or None
		# A discovered server may have no title, but a rename must name it.
		if not self.is_new() and self.has_value_changed("title") and not self.title:
			frappe.throw(_("Enter a server name."))

	def onload(self) -> None:
		self.set_onload("is_access_locked", self.is_access_locked())

	def after_insert(self) -> None:
		# The region accepted a creation. Open consoles list the new server now, not at its first state report.
		self.publish_state_change()

	def on_update(self):
		if self.has_value_changed("status") or self.has_value_changed("plan"):
			self.sync_subscription_on_status_change()

		if self.has_value_changed("status") or self.has_value_changed("public_ipv4"):
			self.sync_public_ipv4_billing()

		if self.has_value_changed("status") and self.status == "Failed":
			self.queue_status_notification("server_failed")

		if self.has_value_changed("status") and self.status == "Terminated":
			self.close_trial()
			self.enqueue_route_removal()
			self.revoke_pilot_credentials()
			UserMailAccount.queue_removal(server=self.name)
			AITrialKey.queue_revoke(server=self.name)
			self.queue_status_notification("server_terminated")

	def close_trial(self) -> None:
		"""A terminated server ends its open trial now, so its owner can start a new trial at once."""
		from central.signups.trial import Trial

		if trial := Trial.find_open(self.name):
			trial.delete()

	def is_access_locked(self) -> bool:
		"""Whether the server runs an open free trial. Its owner then gets the site, not the server."""
		from central.signups.access import is_server_locked

		return is_server_locked(self.name)

	def require_server_access(self, user: str | None = None) -> None:
		"""Refuse SSH, the console, Pilot and snapshots on an open free trial. Operators keep access."""
		from central.signups.access import SERVER_ACCESS_LOCKED

		if self.is_access_locked() and not user_has_operator_bypass(user):
			frappe.throw(str(SERVER_ACCESS_LOCKED), frappe.PermissionError)

	def revoke_pilot_credentials(self) -> None:
		"""A terminated server's Pilot must not reach Central again."""
		for name in frappe.get_all(
			"Pilot Credential", filters={"team": self.team, "server": self.name}, pluck="name"
		):
			PilotCredential.revoke_by_id(name)

	@frappe.whitelist(methods=["POST"])
	def open_bench_as_administrator(self) -> str:
		"""Operator action: a one-click Administrator login to this bench, recorded on the server."""
		frappe.only_for("System Manager")
		url = self.get_bench_login_url(frappe.session.user)
		self.add_comment("Info", _("{0} opened the bench as Administrator.").format(frappe.session.user))
		return url

	@frappe.whitelist(methods=["POST"])
	def retry_admin_domain(self) -> None:
		"""Operator action: ask Pilot for the admin hostname again after it failed."""
		self.check_permission("write")
		if not self.admin_domain_error:
			frappe.throw(_("The admin hostname has no failure to retry."))

		self.claim_admin_hostname()

	@frappe.whitelist(methods=["POST"])
	def revoke_pilot_access(self) -> None:
		"""Operator action: stop this server's Pilot from reaching Central, recorded on the server."""
		frappe.only_for("System Manager")
		self.revoke_pilot_credentials()
		self.add_comment(
			"Info", _("{0} revoked the Pilot credentials of this server.").format(frappe.session.user)
		)

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
		"""Create the subscription if missing, else enable it if disabled. A free trial has none."""
		from central.signups.trial import is_billing_deferred

		if is_billing_deferred(self.name):
			return

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

	def sync_public_ipv4_billing(self) -> None:
		"""Bill a public IPv4 while Atlas reports one on this server, and stop when it is gone."""
		from central.billing.catalog import public_ips

		is_billed = bool(self.public_ipv4) and self.status != "Terminated"
		subscription = frappe.db.get_value("Subscription", {"public_ip_server": self.name, "enabled": 1})
		if is_billed and not subscription:
			public_ips.open_public_ipv4_subscription(self)
		elif subscription and not is_billed:
			public_ips.close_public_ipv4_subscription(subscription)

	def disable_active_subscription(self):
		"""Cancel and disable the team's active subscription for this terminated server.
		The Cancelled change closes the billing segment, so the estimate stops counting the server and
		its headroom is freed. It is safe to repeat."""
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
		"public_ipv6",
		"gateway_url",
		"is_firewall_enabled",
		"firewall_rules",
		"has_ipv4_internet",
		"atlas_host_id",
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
		# Every report moves the observation clock, so keep a Version only for a real change.
		doc.save(ignore_permissions=True, ignore_version=not changed)
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
		"""Read this server's state from the region now. The operator's way to refresh a record
		that looks stale."""
		from central.integrations.servers import observe_server

		self.check_permission("read")

		return {"status": observe_server(self)}

	@requires_server_access
	def get_bench_login_url(self, user: str) -> str:
		"""A login URL for a Running server in an active region, gated on `server:console`.

		The SID is single-use and its audience is this bench's own, so it opens no other bench."""
		if not can(user, self.team, "server:console", server=self.name):
			frappe.throw(_("You can't open servers for this team."), frappe.PermissionError)

		if self.status != "Running":
			frappe.throw(_("Server is {0}, not running.").format(self.status.lower()), frappe.ValidationError)
		if frappe.db.get_value("Region", self.region, "status") != "Active":
			frappe.throw(
				_("This region is not active. Contact support if you need access to this server."),
				frappe.ValidationError,
			)

		gateway = (self.gateway_url or "").rstrip("/")
		if not gateway:
			frappe.throw(
				_(
					"This server has no bench gateway yet. Wait for setup to finish before opening the server dashboard. Contact support if setup does not finish."
				),
				frappe.ValidationError,
			)

		# The bench verifies the SID against its own audience id, which its Pilot Credential holds.
		audience = frappe.db.get_value(
			"Pilot Credential", {"server": self.resource_id, "status": "Active"}, "audience_id"
		)
		if not audience:
			frappe.throw(
				_(
					"This server's Pilot has not enrolled yet. Wait for setup to finish before opening the server dashboard. Contact support if setup does not finish."
				),
				frappe.ValidationError,
			)

		return f"{gateway}/?sid={mint_bench_login(audience)}"

	@requires_server_access
	def set_ssh_keys(self, key_names: list[str]) -> None:
		"""Replace the team keys that can sign in to this server."""
		from central.integrations.ssh_keys import replace_server_ssh_keys
		from central.resource_actions import resolve_team_ssh_keys

		self.require_live()
		replace_server_ssh_keys(self, key_names, resolve_team_ssh_keys(self.team, key_names))

	@requires_server_access
	def set_termination_protection(self, enabled: bool) -> None:
		"""Turn termination protection on or off. The region refuses to terminate a protected server."""
		from central.integrations.servers import set_termination_protection

		self.require_live()
		set_termination_protection(self, enabled)

	def set_public_ip(self, version: int, is_attached: bool) -> bool:
		"""Attach or detach a public address. Returns False while Atlas is still applying it."""
		from central.billing.catalog.public_ips import require_public_ipv4_rate
		from central.integrations.servers import set_public_ip

		self.require_live()
		if version == 4 and is_attached:
			require_public_ipv4_rate(self.team, self.region)

		return set_public_ip(self, version, is_attached)

	def set_ipv4_internet(self, enabled: bool) -> None:
		from central.integrations.servers import set_ipv4_internet

		self.require_live()
		if not enabled and self.public_ipv4:
			frappe.throw(_("Detach the public IPv4 address before you turn off IPv4 internet access."))

		set_ipv4_internet(self, enabled)

	def update_firewall(self, change: FirewallChange) -> None:
		from central.integrations.servers import update_firewall

		self.require_live()
		update_firewall(self, change)

	def require_live(self) -> None:
		if self.status == "Terminated":
			frappe.throw(_("This server is terminated."))

	def publish_state_change(self) -> None:
		"""Tell this team's consoles that one of its servers changed. The payload is identity only,
		and the room is the server's Team, which Frappe checks read permission on before a join."""
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
		except (RequestException, OSError, ValueError):
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
					"admin_domain_diagnostic": None,
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
		self.log_error(title=title, message=diagnostic)
		self.db_set({"admin_domain_error": reason, "admin_domain_diagnostic": f"{title}\n\n{diagnostic}"})

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
	frappe.db.add_unique("Virtual Machine", ["region", "atlas_vm_id"])
	frappe.db.add_index("Virtual Machine", ["team", "status"])
