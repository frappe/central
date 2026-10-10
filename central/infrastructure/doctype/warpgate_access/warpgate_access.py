# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import convert_utc_to_system_timezone, get_datetime, get_system_timezone, now_datetime

from central.errors import AtlasConnectionError
from central.integrations.atlas import AtlasClient

ACCESS_ROLE = "Atlas Host Access"
ADMIN_ROLE = "Atlas Warpgate Admin"
ADMIN = "Admin"
ALL_HOSTS = "all"
WARPGATE_SSH_PORT = 2223
HOST_DURATIONS = {"1 hour": 1, "3 hours": 3, "6 hours": 6, "12 hours": 12, "1 day": 24}
ADMIN_DURATIONS = {
	"1 hour": 1,
	"6 hours": 6,
	"12 hours": 12,
	"1 day": 24,
	"7 days": 24 * 7,
	"30 days": 24 * 30,
	"Never": None,
}


class WarpgateAccess(Document):
	"""Warpgate access to one host, to every host of a region, or to the Warpgate admin UI."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		access_type: DF.Literal["One host", "All hosts", "Admin"]
		amended_from: DF.Link | None
		duration: DF.Literal[
			"1 hour", "3 hours", "6 hours", "12 hours", "1 day", "7 days", "30 days", "Never"
		]
		expires_at: DF.Datetime | None
		host: DF.Data | None
		host_title: DF.Autocomplete | None
		is_revoked: DF.Check
		reason: DF.SmallText | None
		region: DF.Link | None
		status: DF.Literal["", "Active", "Expired", "Cancelled"]
		user: DF.Link
	# end: auto-generated types

	@property
	def is_admin(self) -> bool:
		return self.access_type == ADMIN

	@property
	def durations(self) -> dict[str, int | None]:
		return ADMIN_DURATIONS if self.is_admin else HOST_DURATIONS

	def validate(self) -> None:
		if self.duration not in self.durations:
			frappe.throw(_("{0} access cannot last {1}.").format(self.access_type, self.duration))
		if self.is_admin:
			self.region = self.host = self.host_title = None
			return
		self.validate_user_role()
		self.validate_target()

	def validate_user_role(self) -> None:
		if ACCESS_ROLE not in frappe.get_roles(self.user):
			frappe.throw(_("{0} needs the {1} role to sign in to Warpgate.").format(self.user, ACCESS_ROLE))

	def validate_target(self) -> None:
		if not self.region:
			frappe.throw(_("Select a region."))
		if self.access_type == "All hosts":
			self.host, self.host_title = ALL_HOSTS, None
		elif not self.host or not self.host_title:
			frappe.throw(_("Select a host of region {0}.").format(self.region))

	def before_submit(self) -> None:
		self.validate_no_active_access()
		self.status = "Active"
		self.is_revoked = 0
		hours = self.durations[self.duration]
		self.expires_at = None
		if hours is not None:
			expires_at = datetime.now(UTC) + timedelta(hours=hours)
			self.expires_at = convert_utc_to_system_timezone(expires_at).replace(tzinfo=None)

	def on_submit(self) -> None:
		if self.is_admin:
			frappe.get_doc("User", self.user).add_roles(ADMIN_ROLE)
			return
		expires_at = get_datetime(self.expires_at).replace(tzinfo=ZoneInfo(get_system_timezone()))
		self.get_atlas_client().grant_host_access(self.host, self.email, expires_at)

	def on_cancel(self) -> None:
		self.db_set("status", "Cancelled")
		self.revoke_now()

	def revoke_now(self) -> None:
		"""Revoke, and mark the access revoked. A failed revoke runs again in revoke_ended_access."""
		try:
			self.revoke()
		except AtlasConnectionError:
			# No frame locals: they hold the Atlas bearer token.
			frappe.log_error(
				title=f"Warpgate Access {self.name} was not revoked", message=frappe.get_traceback()
			)
			return
		self.db_set("is_revoked", 1)

	def revoke(self) -> None:
		"""End the access and every live Warpgate session of the person. Revoking twice is safe."""
		if not self.is_admin:
			self.get_atlas_client().revoke_host_access(self.host, self.email)
			return
		frappe.get_doc("User", self.user).remove_roles(ADMIN_ROLE)
		for region in get_warpgate_regions():
			AtlasClient.for_operator(region).close_sessions(self.email)

	def validate_no_active_access(self) -> None:
		"""One active access gives a person each permission, so revoking it always ends that permission."""
		# Lock the person, so two submissions together cannot both pass this check.
		frappe.db.get_value("User", self.user, "name", for_update=True)
		filters = {"docstatus": ["in", [1, 2]], "is_revoked": 0, "user": self.user, "name": ["!=", self.name]}
		if self.is_admin:
			filters["access_type"] = ADMIN
		else:
			filters["access_type"] = ["!=", ADMIN]
			filters["region"] = self.region
			# An all-hosts access overlaps every host of the region. A one-host access overlaps its host and all hosts.
			if self.host != ALL_HOSTS:
				filters["host"] = ["in", [self.host, ALL_HOSTS]]
		# A locking read sees access that committed while this submission waited for the lock.
		active = frappe.db.get_value("Warpgate Access", filters, "name", for_update=True)
		if active:
			frappe.throw(
				_(
					"{0} already gives this access, or its revoke is pending. Cancel it, or wait a minute."
				).format(active)
			)

	@property
	def email(self) -> str:
		return frappe.db.get_value("User", self.user, "email")

	def get_atlas_client(self) -> AtlasClient:
		return AtlasClient.for_operator(frappe.get_doc("Region", self.region))

	@frappe.whitelist(methods=["GET"])
	def get_ssh_command(self) -> str:
		"""The command that opens the host through the regional Warpgate."""
		proxy_domain = frappe.db.get_value("Region", self.region, "proxy_domain")
		if not proxy_domain:
			frappe.throw(_("Region {0} has no proxy domain.").format(self.region))
		target = self.host_title or "<host>"
		return f"ssh -p {WARPGATE_SSH_PORT} {self.email}:{target}@warpgate.{proxy_domain}"


@frappe.whitelist(methods=["GET"])
def get_hosts(region: str) -> list[dict]:
	"""The hosts of one region, for the host field."""
	hosts = AtlasClient.for_operator(frappe.get_doc("Region", region)).list_hosts()
	return [{"id": host["id"], "title": host["title"], "status": host["status"]} for host in hosts]


def get_warpgate_regions() -> list:
	names = frappe.get_all(
		"Region", filters={"base_url": ["is", "set"], "status": ["!=", "Disabled"]}, pluck="name"
	)
	return [frappe.get_doc("Region", name) for name in names]


def revoke_ended_access() -> None:
	"""Mark each access whose end time passed, then revoke each ended access that is not revoked yet."""
	for name in frappe.get_all(
		"Warpgate Access",
		filters={"docstatus": 1, "status": "Active", "expires_at": ["<=", now_datetime()]},
		pluck="name",
	):
		frappe.db.set_value("Warpgate Access", name, "status", "Expired", update_modified=False)
	frappe.db.commit()  # nosemgrep

	for name in frappe.get_all(
		"Warpgate Access",
		filters={"docstatus": ["in", [1, 2]], "status": ["in", ["Expired", "Cancelled"]], "is_revoked": 0},
		pluck="name",
	):
		access = frappe.get_doc("Warpgate Access", name, for_update=True)
		if not access.is_revoked:
			access.revoke_now()
		frappe.db.commit()  # nosemgrep
