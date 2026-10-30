from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

import frappe
from frappe import _
from frappe.model.document import Document

from central.infrastructure.doctype.blocked_domain.blocked_domain import BlockedDomain, normalize_domain
from central.signups.funnel import capture_trial_event

if TYPE_CHECKING:
	from central.infrastructure.doctype.resource_action.resource_action import ResourceAction

IMAGE_SITE_NAME = "site.local"


class Site(Document):
	"""The one site that a Pilot image carries, on the machine that runs it.
	Its address is its name and its state is the machine's, so neither is copied here."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		claimed_at: DF.Datetime | None
		conversion_plan: DF.Link | None
		product: DF.Link | None
		ready_at: DF.Datetime | None
		rename_completed_at: DF.Datetime | None
		rename_diagnostic: DF.Code | None
		rename_error: DF.SmallText | None
		rename_status: DF.Literal["", "queued", "running", "success", "failed", "killed"]
		rename_task: DF.Data | None
		renamed_at: DF.Datetime | None
		server: DF.Link
		site_name: DF.Data
		subdomain: DF.Data | None
		team: DF.Link
		trial_cost: DF.Currency
		trial_currency: DF.Link | None
		trial_deletes_on: DF.Date | None
		trial_ends_on: DF.Date | None
		trial_error: DF.SmallText | None
		trial_last_notice: DF.Data | None
		trial_state: DF.Literal["", "Active", "Ended", "Converted", "Deleted"]
	# end: auto-generated types

	@property
	def rename_target(self) -> str:
		"""The hostname the customer chose, which the bench is renamed onto. Nothing is sent to it
		before the rename lands."""
		_, zone = self.name.split(".", 1)
		return f"{self.subdomain}.{zone}"

	@property
	def url(self) -> str:
		"""The automatic address used for readiness probes and the initial signup handoff."""
		return f"https://{self.name}"

	@property
	def primary_url(self) -> str:
		"""The address the console shows: the customer's subdomain once the rename has landed."""
		return Site.get_primary_url(self.name, self.subdomain, self.renamed_at)

	@property
	def routed_url(self) -> str:
		"""The customer's chosen name once its Site Domain is active, else the primary address. The
		image serves every name in its zone, so the chosen name answers before the rename lands."""
		if self.subdomain and frappe.db.get_value("Site Domain", self.rename_target, "status") == "Active":
			return f"https://{self.rename_target}"
		return self.primary_url

	@staticmethod
	def get_primary_url(name: str, subdomain: str | None, renamed_at: str | None) -> str:
		if not subdomain or not renamed_at:
			return f"https://{name}"
		_, zone = name.split(".", 1)
		return f"https://{subdomain}.{zone}"

	@property
	def status(self) -> str | None:
		"""A site has no lifecycle of its own, so its machine's state is its state."""
		return frappe.db.get_value("Virtual Machine", self.server, "status")

	@classmethod
	def create_once_addressable(cls, server: str) -> None:
		"""Record the site of a machine that has a routable address. It runs on every report and
		writes once; a machine with a site, without Pilot, without an address, or whose image has no
		site is left alone."""
		if frappe.db.exists("Site", {"server": server}):
			return

		machine = frappe.db.get_value(
			"Virtual Machine", server, ["team", "region", "ipv6_address", "has_site"], as_dict=True
		)
		if not machine or not machine.has_site or not machine.ipv6_address:
			return
		if not frappe.db.exists("Pilot Credential", {"server": server, "status": "Active"}):
			return

		host = frappe.get_cached_doc("Region", machine.region).get_vm_site_host(machine.ipv6_address)
		if not host:
			return

		# An imported machine has no create request, so no name or product either.
		action_name = frappe.db.get_value("Resource Action", {"server": server, "action": "create"})
		action = frappe.get_doc("Resource Action", action_name) if action_name else None
		intent = action.get_site_creation() if action else None
		product = intent.product if intent else None
		# The verified region authorizes this record, the same way it authorizes the machine's.
		site = frappe.get_doc(
			{
				"doctype": "Site",
				"site_name": host,
				"subdomain": action.subdomain if action else None,
				"team": machine.team,
				# A product deleted since the request must not stop the site's record.
				"product": product if product and frappe.db.exists("Product", product) else None,
				"server": server,
			}
		)
		# The verified regional server report owns creation of this system mirror.
		site.insert(ignore_permissions=True)

	def before_insert(self) -> None:
		from central.signups.trial import Trial

		Trial(self).start()

	def validate(self) -> None:
		if self.has_value_changed("site_name"):
			BlockedDomain.validate_assignment(self.site_name)
		if self.subdomain and (self.has_value_changed("subdomain") or self.has_value_changed("site_name")):
			self.subdomain = normalize_domain(self.subdomain)
			BlockedDomain.validate_assignment(self.rename_target)

	def before_rename(self, old_name: str, new_name: str, merge: bool = False) -> None:
		BlockedDomain.validate_assignment(new_name)

	def after_insert(self) -> None:
		from central.signups.trial import Trial

		Trial(self).convert_if_paid()
		if self.subdomain:
			frappe.enqueue_doc(
				self.doctype, self.name, "route_subdomain", queue="short", enqueue_after_commit=True
			)

	def route_subdomain(self) -> None:
		"""Route the chosen name to the server now, so the first sign-in can use it before the
		rename lands. A job keeps a refused route from stopping the Site record."""
		if frappe.db.exists("Site Domain", self.rename_target):
			return

		route = frappe.get_doc(
			{
				"doctype": "Site Domain",
				"domain": self.rename_target,
				"team": self.team,
				"server": self.server,
				"site": self.name,
				"region": frappe.db.get_value("Virtual Machine", self.server, "region"),
			}
		)
		# The system routes the name the customer chose at signup; no user acts here.
		route.insert(ignore_permissions=True)

	def mark_claimed(self) -> None:
		"""Record the first successful login handoff and schedule the optional rename."""
		if not self.claimed_at:
			self.db_set("claimed_at", frappe.utils.now_datetime())
			capture_trial_event("trial_claimed", self.team, self.product, user=frappe.session.user)
			from central.activity.sites import record_site_claimed
			record_site_claimed(self)

		self.enqueue_subdomain_rename()

	def record_ready(self) -> None:
		"""Record and announce the first successful probe of the site's public address. The locking
		read keeps the scheduled probe and a console request from both announcing it."""
		if frappe.db.get_value("Site", self.name, "ready_at", for_update=True):
			return

		self.db_set("ready_at", frappe.utils.now_datetime())
		self.capture_ready()
		from central.notification.engine import queue_event

		product = frappe.db.get_value("Product", self.product, "title") if self.product else None
		queue_event(
			self.team,
			"site_ready",
			context={"product": product} if product else None,
			reference_doctype=self.doctype,
			reference_name=self.name,
		)

	def capture_ready(self) -> None:
		"""Send the ready trial to the signup funnel, with how long the customer waited."""
		requested_at = frappe.db.get_value(
			"Resource Action", {"server": self.server, "action": "create"}, "creation"
		)
		capture_trial_event(
			"trial_ready",
			self.team,
			self.product,
			seconds_to_ready=(self.ready_at - requested_at).total_seconds() if requested_at else None,
		)

	def enqueue_subdomain_rename(self) -> None:
		"""Schedule the rename without keeping the login response waiting on Pilot."""
		if not self.subdomain or self.rename_task:
			return

		frappe.enqueue_doc(
			self.doctype,
			self.name,
			"apply_subdomain",
			queue="short",
			enqueue_after_commit=True,
			job_id=f"site-rename:{self.name}",
			deduplicate=True,
		)

	def apply_subdomain(self) -> None:
		"""Submit the site rename without waiting for Pilot to finish it."""
		from central.integrations.pilot import rename_site

		if not self.subdomain or self.rename_task:
			return

		try:
			BlockedDomain.validate_assignment(self.rename_target)
		except frappe.ValidationError as exception:
			self.record_rename_failure(str(exception), frappe.get_traceback(with_context=False))
			return

		try:
			task = rename_site(self.server, IMAGE_SITE_NAME, self.rename_target, make_primary=True)
		# This worker boundary records every failure so an operator can retry it safely.
		except Exception:
			self.record_rename_failure(
				_("Pilot did not accept the site rename. Retry it from this Site."),
				frappe.get_traceback(with_context=False),
			)
			return

		task_id = task.get("task_id") if isinstance(task, dict) else None
		if not task_id:
			self.record_rename_failure(
				_("Pilot did not return a task for the site rename. Retry it from this Site."),
				frappe.as_json(task),
			)
			return

		self.db_set(
			{
				"rename_task": task_id,
				"rename_status": "queued",
				"rename_completed_at": None,
				"rename_error": None,
				"rename_diagnostic": None,
			}
		)

	def record_rename_status(self) -> None:
		"""Record Pilot's rename outcome without waiting in the signup request."""
		from central.integrations.pilot import get_task

		if not self.rename_task or self.rename_status not in {"queued", "running"}:
			return
		task_id = self.rename_task
		task = get_task(self.server, task_id)

		updates = {"rename_status": task["status"]}
		if task["status"] == "success":
			updates.update(
				rename_completed_at=frappe.utils.now_datetime(), rename_error=None, rename_diagnostic=None
			)
		elif task["status"] in {"failed", "killed"}:
			updates.update(
				rename_error=_("Pilot did not complete the site rename. Inspect the task in Pilot."),
				rename_diagnostic=frappe.as_json(task.get("failure")),
			)
		frappe.db.set_value(
			"Site",
			{"name": self.name, "rename_task": task_id, "rename_status": ["in", ["queued", "running"]]},
			updates,
		)

	def record_rename_failure(self, reason: str, diagnostic: str) -> None:
		"""Keep a safe reason and the operator diagnostic on the Site."""
		self.log_error(title="Pilot site rename failed", message=diagnostic)
		self.db_set(
			{"rename_error": reason, "rename_diagnostic": f"Pilot site rename failed\n\n{diagnostic}"}
		)

	@frappe.whitelist(methods=["POST"])
	def retry_subdomain_rename(self) -> None:
		"""Operator action: retry a rename that Pilot did not accept."""
		self.check_permission("write")
		if self.rename_task:
			frappe.throw(_("Pilot already accepted this site rename."))
		if not self.rename_error:
			frappe.throw(_("This site rename has no recorded failure."))

		self.db_set({"rename_error": None, "rename_diagnostic": None})
		self.enqueue_subdomain_rename()

	@frappe.whitelist(methods=["POST"])
	def extend_trial(self, days: int) -> None:
		"""Operator action: give the trial more days, and start an ended trial again."""
		from central.signups.trial import Trial

		frappe.only_for("System Manager")
		Trial(self).extend(days)
		self.add_comment("Info", _("{0} extended the trial by {1} days.").format(frappe.session.user, days))

	@frappe.whitelist(methods=["POST"])
	def end_trial_now(self) -> None:
		"""Operator action: end an active trial today. Its server stops."""
		from central.signups.trial import Trial

		frappe.only_for("System Manager")
		Trial(self).end(frappe.utils.getdate())
		self.add_comment("Info", _("{0} ended the trial.").format(frappe.session.user))

	@frappe.whitelist(methods=["POST"])
	def retry_trial_step(self) -> None:
		"""Operator action: run today's trial step again after a failure."""
		from central.signups.trial import Trial

		frappe.only_for("System Manager")
		self.db_set("trial_error", None)
		Trial(self).advance(frappe.utils.getdate())

	@frappe.whitelist(methods=["POST"])
	def open_as_administrator(self) -> str | None:
		"""Operator action: a one-click login to this site, recorded on the site and its server."""
		from central.integrations.pilot import PilotLoginPending

		frappe.only_for("System Manager")
		try:
			url = self.get_login_url(frappe.session.user)
		except PilotLoginPending:
			frappe.throw(_("Pilot could not create a login yet. Try again in a minute."))
		note = _("{0} opened site {1} as Administrator.").format(frappe.session.user, self.name)
		self.add_comment("Info", note)
		frappe.get_doc("Virtual Machine", self.server).add_comment("Info", note)
		return url

	@frappe.whitelist(methods=["POST"])
	def check_readiness(self) -> bool:
		"""Operator action: probe the site's address now, and record readiness when it answers."""
		from central.integrations.pilot import is_site_reachable

		self.check_permission("read")
		is_ready = is_site_reachable(self.url)
		if is_ready:
			self.record_ready()

		return is_ready

	def get_login_url(self, user: str | None = None, product: str | None = None) -> str | None:
		"""A one-click session for `user`, or for Administrator, on the site's public address.
		Use the customer hostname once it answers, and the automatic address until then.
		It lands on the page of `product`, or of the site's own product."""
		from central.integrations.pilot import fetch_site_login_url, is_site_reachable

		gateway, audience = self.get_pilot_access()
		if not gateway or not audience:
			return None

		login_user, full_name = self.get_login_user(user)
		# The image serves every name in its zone, so the chosen name answers once its route does.
		is_chosen_name_ready = bool(self.subdomain) and is_site_reachable(f"https://{self.rename_target}")
		if is_chosen_name_ready and not self.renamed_at:
			self.db_set("renamed_at", frappe.utils.now_datetime())
		host = self.rename_target if is_chosen_name_ready else self.name
		pilot_names = self.get_pilot_site_names() if is_chosen_name_ready else [IMAGE_SITE_NAME]
		for pilot_name in pilot_names:
			if minted := fetch_site_login_url(gateway, audience, pilot_name, login_user, full_name):
				return on_host(minted, host, self.get_landing_route(product))

		return None

	def get_landing_route(self, product: str | None = None) -> str | None:
		"""The product's page, where the app runs its own setup, instead of Desk."""
		product = product or self.product
		return frappe.db.get_value("Product", product, "landing_route") if product else None

	def get_pilot_site_names(self) -> list[str]:
		"""Try the stable image name first, then the name of a previously renamed site."""
		return (
			[IMAGE_SITE_NAME, self.rename_target]
			if self.subdomain and self.rename_task
			else [IMAGE_SITE_NAME]
		)

	def get_login_user(self, user: str | None) -> tuple[str | None, str | None]:
		"""Who `user` signs in as: themselves on a trial site of their team, otherwise
		Administrator, shown as (None, None).

		1. Only a trial site is for its owner. Others, such as a bought server's, keep Administrator.
		2. An operator outside the team never gets a user on a customer's site."""
		from central.iam import get_user_team_names

		if not user or not self.is_trial() or self.team not in get_user_team_names(user):
			return None, None

		return user, frappe.db.get_value("User", user, "full_name")

	def is_trial(self) -> bool:
		request = self.get_creation_request()
		return bool(request and request.get_site_creation())

	def get_creation_request(self) -> ResourceAction | None:
		name = frappe.db.get_value("Resource Action", {"server": self.server, "action": "create"})
		return frappe.get_doc("Resource Action", name) if name else None

	def get_pilot_access(self) -> tuple[str | None, str | None]:
		"""The machine's gateway and the audience its Pilot verifies tokens against.

		Nothing here waits for the machine's mirrored status: the site probe that gates
		every caller of this method already proved the machine answers."""
		gateway = frappe.db.get_value(
			"Virtual Machine", {"name": self.server, "team": self.team}, "gateway_url"
		)
		audience = frappe.db.get_value(
			"Pilot Credential", {"server": self.server, "team": self.team, "status": "Active"}, "audience_id"
		)

		return (gateway.rstrip("/") if gateway else None), audience


def record_ready_sites() -> None:
	"""Scheduled job: probe each running trial site that has not answered yet, so readiness and
	its email do not wait for the customer to come back. A sleeping server is not Running, so the
	probe does not wake it. Other sites record readiness when someone opens them."""
	from central.integrations.pilot import is_site_reachable

	for name in frappe.get_all(
		"Site",
		filters={"trial_state": "Active", "ready_at": ["is", "not set"], "server.status": "Running"},
		pluck="name",
	):
		site = frappe.get_doc("Site", name)
		if is_site_reachable(site.url):
			site.record_ready()
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- keep each site's readiness if a later probe fails


def poll_site_renames() -> None:
	"""Record pending rename outcomes without one failed check stopping the rest."""
	for name in frappe.get_all(
		"Site",
		filters={"rename_status": ["in", ["queued", "running"]], "server.status": "Running"},
		pluck="name",
	):
		try:
			frappe.get_doc("Site", name).record_rename_status()
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- preserve each observed outcome
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				title="Could not read Pilot rename task", reference_doctype="Site", reference_name=name
			)


def on_host(url: str, host: str, path: str | None = None) -> str:
	"""The same request on another host, and on `path` when given. The scheme is always
	https, because the public name exists only behind the regional proxy, which terminates
	TLS. Frappe reads the session from the query on any path."""
	minted = urlsplit(url)
	return urlunsplit(("https", host, path or minted.path, minted.query, minted.fragment))


def get_server_hostnames(team: str, server: str | None) -> list[str]:
	"""Every hostname the team's sites on `server` answer on: each site's own address and its
	routed domains. The console's `server_hostnames` also lists routes that are not active."""
	if not server:
		return []

	filters = {"team": team, "server": server}
	sites = frappe.get_all("Site", filters=filters, pluck="name")
	domains = frappe.get_all("Site Domain", filters={**filters, "status": "Active"}, pluck="name")

	return sorted({*sites, *domains})


def on_doctype_update():
	# The fleet reads a team's sites, then drops the machine each one already stands for.
	frappe.db.add_index("Site", ["team", "server"])
	frappe.db.add_index("Site", ["product"])
	frappe.db.add_index("Site", ["rename_status", "modified"])
	# The daily trial job reads trials by state and the day they end.
	frappe.db.add_index("Site", ["trial_state", "trial_ends_on"])
