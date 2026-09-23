# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

from typing import TYPE_CHECKING

import dns.exception
import dns.resolver
import frappe
import httpx
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from central.infrastructure.doctype.region.atlas_connection import is_auto_routed_label
from central.infrastructure.doctype.region.region import REGIONAL_SERVICES, Region
from central.integrations.proxy import ProxyError

if TYPE_CHECKING:
	from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential

MAXIMUM_ATTEMPTS = 5
VERIFICATION_TTL_SECONDS = 24 * 60 * 60
VERIFICATION_RECORD = "_frappe-verification"


class DomainNotVerifiedError(frappe.ValidationError):
	http_status_code = 409


class SiteDomain(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		server: DF.Link
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

	@property
	def has_auto_routed_name(self) -> bool:
		"""True when the region answers this hostname from its label, so the proxy holds no key."""
		return self.route_type == "Site" and is_auto_routed_label(self.site_label)

	@property
	def is_auto_routed(self) -> bool:
		"""True when the region routes this hostname to this server from the label alone."""
		return self.has_auto_routed_name and self.domain in self.get_auto_routed_hosts()

	def before_naming(self) -> None:
		self.domain = normalize_domain(self.domain)

	def validate(self) -> None:
		self.route_type = self.get_route_type()
		self.validate_targets()
		self.validate_auto_routed_host()
		if self.has_auto_routed_name:
			frappe.throw(_("The region routes {0} already. It needs no route record.").format(self.domain))

	def after_insert(self) -> None:
		frappe.enqueue_doc(self.doctype, self.name, "apply", enqueue_after_commit=True)

	def on_trash(self) -> None:
		if self.has_auto_routed_name:
			return

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
		server = frappe.db.get_value("Virtual Machine", self.server, ["team", "cluster"], as_dict=True)
		if not server or server.team != self.team:
			frappe.throw(_("Server {0} does not belong to team {1}.").format(self.server, self.team))
		if server.cluster != self.region:
			frappe.throw(_("Server {0} is not in region {1}.").format(self.server, self.region))
		if self.site and frappe.db.get_value("Site", self.site, "team") != self.team:
			frappe.throw(_("Site {0} does not belong to team {1}.").format(self.site, self.team))

	def get_auto_routed_hosts(self) -> set[str]:
		"""The hostnames the region routes to this server with no map entry of their own.

		The proxy reads the mesh address out of the base-36 token in the label, so both names
		follow from the server itself."""
		instance = frappe.get_cached_doc("Region", self.region)
		address = frappe.db.get_value("Virtual Machine", self.server, "ipv6_address")
		hosts = (instance.get_vm_admin_host(address), instance.get_vm_site_host(address))
		return {host for host in hosts if host}

	def validate_auto_routed_host(self) -> None:
		"""Refuse a label of the routed shape that names a different server. The proxy answers
		it from the label, so no record here could ever bring it to this server."""
		if self.has_auto_routed_name and not self.is_auto_routed:
			frappe.throw(_("The region routes {0} to another server.").format(self.domain))

	def apply(self) -> None:
		"""Send this route to the regional proxy and record the outcome. Safe to repeat.
		A terminated server's route is removed instead."""
		address, status = frappe.db.get_value("Virtual Machine", self.server, ["ipv6_address", "status"])
		if status == "Terminated":
			self.remove()
			return

		values = {"attempts": self.attempts + 1, "last_attempt_at": now_datetime()}
		try:
			if not address:
				raise ProxyError(_("Server {0} has no IPv6 address yet.").format(self.server))
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

	def remove(self) -> None:
		"""Delete this route and its proxy entry. A proxy failure stays on the record, and
		`retry_failed` tries again."""
		try:
			# The server is gone, so the system removes its routes; no user acts here.
			frappe.delete_doc("Site Domain", self.name, ignore_permissions=True)
		# ProxyError and missing regional config are both ValidationErrors.
		except frappe.ValidationError as exception:
			self.db_set(
				{
					"status": "Failed",
					"failure_reason": str(exception),
					"attempts": self.attempts + 1,
					"last_attempt_at": now_datetime(),
				}
			)

	@staticmethod
	def new_for_pilot(credential: PilotCredential, domain: str) -> SiteDomain:
		"""An unsaved route to the Pilot's own server. The server never comes from the request.

		A Pilot only knows its machine, so the site comes from the machine: one machine runs
		one site, which is what lets the console show a domain against the site it reaches."""
		if not credential.server:
			frappe.throw(_("This Pilot has no server yet."))

		route = frappe.get_doc(
			{
				"doctype": "Site Domain",
				"domain": normalize_domain(domain),
				"team": credential.team,
				"server": credential.server,
				"site": frappe.db.get_value("Site", {"server": credential.server}, "name"),
				"region": frappe.db.get_value("Virtual Machine", credential.server, "cluster"),
			}
		)
		route.route_type = route.get_route_type()
		return route

	@staticmethod
	def get_dns_records(credential: PilotCredential, domain: str) -> dict:
		"""DNS records a customer sets before the Pilot registers a custom domain. A site needs none."""
		route = SiteDomain.new_for_pilot(credential, domain)
		if route.route_type == "Site":
			return {}

		key = route.get_verification_key(credential)
		token = frappe.cache.get_value(key)
		if not token:
			token = frappe.generate_hash(length=32)
			frappe.cache.set_value(key, token, expires_in_sec=VERIFICATION_TTL_SECONDS)

		return {
			"cname": [
				{"type": "CNAME", "host": route.domain, "value": route.get_proxy_host()},
				{"type": "TXT", "host": f"{VERIFICATION_RECORD}.{route.domain}", "value": token},
			]
		}

	@staticmethod
	def register(credential: PilotCredential, domain: str) -> None:
		"""Route a domain to the Pilot's server once it is verified. Returns only when the route is live.

		A hostname the region routes from its own label is live already and takes no record."""
		route = SiteDomain.new_for_pilot(credential, domain)
		route.validate_auto_routed_host()
		if route.is_auto_routed:
			return

		if frappe.db.exists("Site Domain", route.domain):
			route = frappe.get_doc("Site Domain", route.domain)
			if route.server != credential.server:
				frappe.throw(_("{0} is already taken.").format(route.domain), frappe.DuplicateEntryError)
		else:
			if route.route_type == "Domain":
				route.verify_ownership(credential)
			# The Pilot credential already proves the server; the request runs as Guest.
			route.insert(ignore_permissions=True)

		route.apply()
		if route.status != "Active":
			frappe.throw(route.failure_reason, ProxyError)

		frappe.cache.delete_value(route.get_verification_key(credential))

	@staticmethod
	def deregister(credential: PilotCredential, domain: str) -> None:
		"""Remove the route of the Pilot's server. A missing route is already removed."""
		name = normalize_domain(domain)
		server = frappe.db.get_value("Site Domain", name, "server")
		if not server:
			return
		if server != credential.server:
			frappe.throw(_("{0} belongs to another server.").format(name), frappe.PermissionError)

		# The Pilot credential already proves the server; the request runs as Guest.
		frappe.delete_doc("Site Domain", name, ignore_permissions=True)

	def get_verification_key(self, credential: PilotCredential) -> str:
		return f"site-domain||{self.domain}||{credential.pilot_credential_id}||verification-token"

	def get_proxy_host(self) -> str:
		return f"proxy.{Region.get_zone(self.region)}"

	def verify_ownership(self, credential: PilotCredential) -> None:
		"""Refuse a custom domain until its DNS proves that the customer controls it."""
		token = frappe.cache.get_value(self.get_verification_key(credential))
		if not token:
			frappe.throw(
				_("Generate the DNS records for {0} first.").format(self.domain), DomainNotVerifiedError
			)

		if token not in _resolve(f"{VERIFICATION_RECORD}.{self.domain}", "TXT"):
			frappe.throw(
				_("The TXT record for {0} is not set yet.").format(self.domain), DomainNotVerifiedError
			)

		# An apex cannot hold a CNAME and DNS providers flatten it, so only a subdomain is checked.
		# TODO: replace this CNAME check with /.well-known/pre-authorize, served by the proxy.
		if not is_apex(self.domain) and self.get_proxy_host() not in _resolve(self.domain, "CNAME"):
			frappe.throw(
				_("The CNAME record for {0} does not point to {1} yet.").format(
					self.domain, self.get_proxy_host()
				),
				DomainNotVerifiedError,
			)

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


def remove_server_routes(server: str) -> None:
	"""Background job: remove every route of a terminated server."""
	for name in frappe.get_all("Site Domain", filters={"server": server}, pluck="name"):
		frappe.get_doc("Site Domain", name).remove()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- keep each outcome if a later route crashes the job


def normalize_domain(domain: str | None) -> str:
	return (domain or "").strip().strip(".").lower()


def is_apex(domain: str) -> bool:
	"""True when the domain is the root of its own DNS zone, such as example.com."""
	return dns.resolver.zone_for_name(domain).to_text().rstrip(".").lower() == domain


def _resolve(name: str, record_type: str) -> list[str]:
	"""The values of one DNS record set, normalized for comparison. Empty when the name has none."""
	try:
		answer = dns.resolver.resolve(name, record_type)
	except dns.resolver.NXDOMAIN, dns.resolver.NoAnswer:
		return []
	except dns.exception.DNSException as exception:
		frappe.throw(_("Could not look up {0}: {1}").format(name, exception), DomainNotVerifiedError)

	if record_type == "TXT":
		return [b"".join(record.strings).decode() for record in answer]
	return [record.to_text().rstrip(".").lower() for record in answer]


def on_doctype_update():
	frappe.db.add_index("Site Domain", ["status", "attempts"])
