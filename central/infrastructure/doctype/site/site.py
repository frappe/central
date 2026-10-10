from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.telemetry import capture

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
		product: DF.Link | None
		ready_at: DF.Datetime | None
		rename_error: DF.SmallText | None
		rename_error_log: DF.Link | None
		rename_task: DF.Data | None
		server: DF.Link
		site_name: DF.Data
		subdomain: DF.Data | None
		team: DF.Link
	# end: auto-generated types

	@property
	def rename_target(self) -> str:
		"""The hostname the customer chose, which the bench is renamed onto. Nothing is sent to it
		before the rename lands."""
		_, zone = self.name.split(".", 1)
		return f"{self.subdomain}.{zone}"

	@property
	def url(self) -> str:
		"""The address the region derives from the machine. It answers before and after the rename,
		so every probe and sign-in uses it."""
		return f"https://{self.name}"

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

	def mark_claimed(self) -> None:
		"""Record the first successful login handoff and schedule the optional rename."""
		if not self.claimed_at:
			self.db_set("claimed_at", frappe.utils.now_datetime())
			capture("trial_claimed", "central", properties={"product": self.product})

		self.enqueue_subdomain_rename()

	def record_ready(self) -> None:
		"""Record and announce the first successful probe of the site's public address."""
		if self.ready_at:
			return

		self.db_set("ready_at", frappe.utils.now_datetime())
		self.capture_ready()
		from central.notification.engine import queue_event

		queue_event(
			self.team,
			"site_ready",
			reference_doctype=self.doctype,
			reference_name=self.name,
		)

	def capture_ready(self) -> None:
		"""Send the ready trial to the signup funnel, with how long the customer waited."""
		requested_at = frappe.db.get_value(
			"Resource Action", {"server": self.server, "action": "create"}, "creation"
		)
		capture(
			"trial_ready",
			"central",
			user=frappe.get_cached_value("Team", self.team, "owner_user"),
			properties={
				"product": self.product,
				"seconds_to_ready": (self.ready_at - requested_at).total_seconds() if requested_at else None,
			},
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
		"""Rename the bench onto the customer's chosen name, once. It returns when Pilot accepts
		the rename, and both hostnames serve until it finishes."""
		from central.integrations.pilot import rename_site

		if not self.subdomain or self.rename_task:
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

		self.db_set({"rename_task": task_id, "rename_error": None, "rename_error_log": None})

	def record_rename_failure(self, reason: str, diagnostic: str) -> None:
		"""Keep a safe reason on the Site and the diagnostic in Error Log."""
		error_log = self.log_error(title="Pilot site rename failed", message=diagnostic)
		self.db_set({"rename_error": reason, "rename_error_log": error_log.name})

	@frappe.whitelist(methods=["POST"])
	def retry_subdomain_rename(self) -> None:
		"""Operator action: retry a rename that Pilot did not accept."""
		self.check_permission("write")
		if self.rename_task:
			frappe.throw(_("Pilot already accepted this site rename."))
		if not self.rename_error:
			frappe.throw(_("This site rename has no recorded failure."))

		self.db_set({"rename_error": None, "rename_error_log": None})
		self.enqueue_subdomain_rename()

	def get_login_url(self, user: str | None = None) -> str | None:
		"""A one-click session for `user`, or for Administrator, on the site's public address.
		Pilot accepts a token only for the site's name on the bench: the customer's name after the
		rename, the image alias before it."""
		from central.integrations.pilot import fetch_site_login_url

		gateway, audience = self.get_pilot_access()
		if not gateway or not audience:
			return None

		login_user, full_name = self.get_login_user(user)
		pilot_names = [self.rename_target, IMAGE_SITE_NAME] if self.rename_task else [IMAGE_SITE_NAME]
		for pilot_name in pilot_names:
			if minted := fetch_site_login_url(gateway, audience, pilot_name, login_user, full_name):
				return on_host(minted, self.name, self.get_landing_route())

		return None

	def get_landing_route(self) -> str | None:
		"""The product's page, where the app runs its own setup, instead of Desk."""
		return frappe.db.get_value("Product", self.product, "landing_route") if self.product else None

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
