# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import convert_utc_to_system_timezone, get_datetime, get_system_timezone, now_datetime

from central.integrations.atlas import AtlasClient

ACCESS_ROLE = "Atlas Host Access"
ALL_HOSTS = "all"
WARPGATE_SSH_PORT = 2223


class HostAccessGrant(Document):
	"""A time-limited SSH grant to one host, or to every host, of a region through Warpgate."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amended_from: DF.Link | None
		duration_hours: DF.Literal["1", "3", "6", "12", "24"]
		expires_at: DF.Datetime | None
		host: DF.Data | None
		host_title: DF.Autocomplete | None
		reason: DF.SmallText | None
		region: DF.Link
		scope: DF.Literal["One host", "All hosts"]
		user: DF.Link
	# end: auto-generated types

	def validate(self) -> None:
		self.validate_user_role()
		self.validate_target()

	def validate_user_role(self) -> None:
		if ACCESS_ROLE not in frappe.get_roles(self.user):
			frappe.throw(_("{0} needs the {1} role to sign in to Warpgate.").format(self.user, ACCESS_ROLE))

	def validate_target(self) -> None:
		if self.scope == "All hosts":
			self.host, self.host_title = ALL_HOSTS, None
		elif not self.host or not self.host_title:
			frappe.throw(_("Select a host of region {0}.").format(self.region))

	def before_submit(self) -> None:
		self.validate_no_active_grant()
		expires_at = datetime.now(UTC) + timedelta(hours=int(self.duration_hours))
		self.expires_at = convert_utc_to_system_timezone(expires_at).replace(tzinfo=None)

	def on_submit(self) -> None:
		expires_at = get_datetime(self.expires_at).replace(tzinfo=ZoneInfo(get_system_timezone()))
		self.get_atlas_client().grant_host_access(self.host, self.email, expires_at)

	def on_cancel(self) -> None:
		self.get_atlas_client().revoke_host_access(self.host, self.email)

	def validate_no_active_grant(self) -> None:
		"""One active grant opens a host to a person, so cancelling it always ends that access."""
		# Lock the person, so two grants submitted together cannot both pass this check.
		frappe.db.get_value("User", self.user, "name", for_update=True)
		filters = {
			"docstatus": 1,
			"user": self.user,
			"region": self.region,
			"expires_at": [">", now_datetime()],
			"name": ["!=", self.name],
		}
		# An all-hosts grant overlaps every grant in the region. A one-host grant overlaps its host and all hosts.
		if self.host != ALL_HOSTS:
			filters["host"] = ["in", [self.host, ALL_HOSTS]]
		# A locking read sees grants that committed while this submission waited for the lock.
		active = frappe.db.get_value("Host Access Grant", filters, "name", for_update=True)
		if active:
			frappe.throw(
				_("{0} already gives access to this host. Cancel or amend it instead.").format(active)
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
