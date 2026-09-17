# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
import httpx
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from central.central.doctype.region.region import REGIONAL_SERVICES, Region
from central.integrations.proxy import ProxyError

MAXIMUM_ATTEMPTS = 5


class SiteDomain(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		asset: DF.Link
		attempts: DF.Int
		domain: DF.Data
		failure_reason: DF.SmallText | None
		ipv6_address: DF.Data | None
		last_attempt_at: DF.Datetime | None
		region: DF.Link
		route_type: DF.Literal["Site", "Domain"]
		site: DF.Link | None
		status: DF.Literal["Pending", "Active", "Failed"]
		team: DF.Link
	# end: auto-generated types

	@property
	def site_label(self) -> str:
		"""The site key in the proxy: the first label of the domain."""
		return self.domain.split(".", 1)[0]

	def before_naming(self) -> None:
		self.domain = (self.domain or "").strip().strip(".").lower()

	def validate(self) -> None:
		self.route_type = self.get_route_type()
		self.validate_targets()

	def after_insert(self) -> None:
		frappe.enqueue_doc(self.doctype, self.name, "apply", enqueue_after_commit=True)

	def on_trash(self) -> None:
		client = Region.get_proxy_client(self.region)
		try:
			if self.route_type == "Site":
				client.delete_site(self.site_label)
			else:
				client.delete_domain(self.domain)
		except (ProxyError, httpx.HTTPError) as exception:
			frappe.throw(
				_("Could not remove {0} from the proxy: {1}").format(self.domain, exception), ProxyError
			)

	def get_route_type(self) -> str:
		"""Site for one label below the regional zone, Domain for anything outside it."""
		zone = Region.get_zone(self.region)
		if self.domain.startswith("*"):
			frappe.throw(_("A wildcard domain cannot be routed."))
		if self.domain == zone:
			frappe.throw(_("The regional zone {0} itself cannot be routed.").format(zone))
		if not self.domain.endswith(f".{zone}"):
			return "Domain"

		label = self.domain.removesuffix(f".{zone}")
		if "." in label:
			frappe.throw(_("A site must be one label below {0}.").format(zone))
		if label in REGIONAL_SERVICES or label.startswith("proxy-"):
			frappe.throw(_("The site name {0} is reserved.").format(label))
		return "Site"

	def validate_targets(self) -> None:
		"""The server and site must belong to this team, and the server to this region."""
		asset = frappe.db.get_value("Asset", self.asset, ["team", "cluster"], as_dict=True)
		if not asset or asset.team != self.team:
			frappe.throw(_("Server {0} does not belong to team {1}.").format(self.asset, self.team))
		if asset.cluster != self.region:
			frappe.throw(_("Server {0} is not in region {1}.").format(self.asset, self.region))
		if self.site and frappe.db.get_value("Site", self.site, "team") != self.team:
			frappe.throw(_("Site {0} does not belong to team {1}.").format(self.site, self.team))

	def apply(self) -> None:
		"""Send this route to the regional proxy and record the outcome. Safe to repeat."""
		address = frappe.db.get_value("Asset", self.asset, "ipv6_address")
		values = {"attempts": self.attempts + 1, "last_attempt_at": now_datetime()}
		try:
			if not address:
				raise ProxyError(_("Server {0} has no IPv6 address yet.").format(self.asset))
			client = Region.get_proxy_client(self.region)
			if self.route_type == "Site":
				client.set_site(self.site_label, address)
			else:
				client.set_domain(self.domain, address)
		# ProxyError and missing regional config are both ValidationErrors.
		except (frappe.ValidationError, httpx.HTTPError) as exception:
			values.update(status="Failed", failure_reason=str(exception))
		else:
			values.update(status="Active", failure_reason=None, attempts=0, ipv6_address=address)

		self.db_set(values)

	@frappe.whitelist()
	def retry(self) -> None:
		"""Operator action: reset the attempt count and send the route again."""
		self.check_permission("write")
		self.db_set("attempts", 0)
		self.apply()


def retry_failed() -> None:
	"""Scheduler: send every route that is not Active yet, until it reaches the attempt limit."""
	names = frappe.get_all(
		"Site Domain",
		filters={"status": ["in", ["Pending", "Failed"]], "attempts": ["<", MAXIMUM_ATTEMPTS]},
		pluck="name",
	)
	for name in names:
		frappe.get_doc("Site Domain", name).apply()
		frappe.db.commit()  # keep each outcome if a later route crashes the job


def on_doctype_update():
	frappe.db.add_index("Site Domain", ["status", "attempts"])
