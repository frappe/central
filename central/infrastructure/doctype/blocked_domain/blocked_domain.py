from __future__ import annotations

from pathlib import Path

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.types import DF

from central.iam import user_has_operator_bypass
from central.server_models import DNS_LABEL


class BlockedDomain(Document):
	"""Operator policy for customer names inside one domain scope."""

	blocked_name: DF.Data
	parent_domain: DF.Data
	match_mode: DF.Literal["Exact", "Prefix"]
	enabled: DF.Check

	def validate(self) -> None:
		self.blocked_name = normalize_domain(self.blocked_name)
		self.parent_domain = normalize_domain(self.parent_domain)
		for value, is_prefix in (
			(self.parent_domain, False),
			(self.blocked_name, self.match_mode == "Prefix"),
		):
			# A prefix can end with a hyphen, as in proxy-.
			candidate = value.rstrip("-") if is_prefix else value
			if not candidate or not all(DNS_LABEL.fullmatch(label) for label in candidate.split(".")):
				frappe.throw(_("Use a domain name without a wildcard, URL, or port."))

	def matches(self, domain: str) -> bool:
		"""Match a relative name only inside this parent domain."""
		if not self.enabled:
			return False
		domain = normalize_domain(domain)
		suffix = f".{self.parent_domain}"
		if not domain.endswith(suffix):
			return False

		relative_name = domain.removesuffix(suffix)
		if self.match_mode == "Prefix":
			return relative_name.startswith(self.blocked_name)
		return relative_name == self.blocked_name

	@staticmethod
	def is_blocked(domain: str) -> bool:
		"""Read global operator policy for a customer assignment, regardless of their roles."""
		labels = normalize_domain(domain).split(".")
		parents = [".".join(labels[index:]) for index in range(1, len(labels))]
		if not parents:
			return False

		# Global policy is a system read; customers cannot list the configuration itself.
		reservations = frappe.get_all(
			"Blocked Domain",
			filters={"enabled": 1, "parent_domain": ["in", parents]},
			fields=["blocked_name", "parent_domain", "match_mode", "enabled"],
		)
		return any(
			BlockedDomain({"doctype": "Blocked Domain", **row}).matches(domain) for row in reservations
		)

	@staticmethod
	def validate_assignment(domain: str) -> None:
		if BlockedDomain.is_blocked(domain):
			frappe.throw(
				_("The domain {0} is reserved. Choose another name.").format(normalize_domain(domain))
			)

	@frappe.whitelist()
	def find_conflicts(self) -> list[dict]:
		"""List existing assignments for operator review without changing them."""
		if not user_has_operator_bypass():
			frappe.throw(_("Only a System Manager can review blocked domains."), frappe.PermissionError)
		self.check_permission("read")
		conflicts = []
		for row in frappe.get_list("Site Domain", fields=["name", "domain", "team"], limit_page_length=0):
			if self.matches(row.domain):
				conflicts.append({"doctype": "Site Domain", **row})
		for row in frappe.get_list("Site", fields=["name", "subdomain", "team"], limit_page_length=0):
			domains = {row.name}
			if row.subdomain and "." in row.name:
				domains.add(f"{row.subdomain}.{row.name.split('.', 1)[1]}")
			for domain in sorted(domains):
				if self.matches(domain):
					conflicts.append(
						{"doctype": "Site", "name": row.name, "domain": domain, "team": row.team}
					)
		return conflicts + self.get_pending_conflicts()

	def get_pending_conflicts(self) -> list[dict]:
		from central.infrastructure.doctype.resource_action.resource_action import PENDING_STATES

		zones = {
			row.name: row.proxy_domain
			for row in frappe.get_list("Region", fields=["name", "proxy_domain"], limit_page_length=0)
		}
		conflicts = []
		for row in frappe.get_list(
			"Resource Action",
			filters={"action": "create", "status": ["in", PENDING_STATES], "subdomain": ["is", "set"]},
			fields=["name", "region", "subdomain", "team"],
			limit_page_length=0,
		):
			domain = f"{row.subdomain}.{zones.get(row.region)}"
			if self.matches(domain):
				conflicts.append(
					{"doctype": "Resource Action", "name": row.name, "domain": domain, "team": row.team}
				)
		return conflicts


def normalize_domain(domain: str | None) -> str:
	return (domain or "").strip().rstrip(".").lower()


def seed_for_zone(zone: str | None) -> None:
	"""Store initial reservations once for a newly configured service zone."""
	if not zone:
		return
	zone = normalize_domain(zone)
	defaults: dict[str, list[str]] = frappe.parse_json(Path(__file__).with_name("defaults.json").read_text())
	existing = set(frappe.get_all("Blocked Domain", filters={"parent_domain": zone}, pluck="blocked_name"))
	for match_mode, names in defaults.items():
		for blocked_name in names:
			if blocked_name in existing:
				continue
			values = {"blocked_name": blocked_name, "parent_domain": zone, "match_mode": match_mode}
			# System configuration follows the region, including when a migration creates it.
			frappe.get_doc({"doctype": "Blocked Domain", "enabled": 1, **values}).insert(
				ignore_permissions=True
			)


def seed_regional_domains() -> None:
	"""Install, migration, and settings hook: add missing defaults in each configured zone."""
	from central.infrastructure.doctype.region.region import Region

	wildcard_domain = frappe.db.get_single_value("Central Settings", "wildcard_domain")
	for region in frappe.get_all("Region", fields=["name", "proxy_domain"]):
		seed_for_zone(region.proxy_domain)
		if wildcard_domain:
			seed_for_zone(Region.get_zone(region.name))


def on_doctype_update() -> None:
	frappe.db.add_index("Blocked Domain", ["parent_domain", "enabled"])
	frappe.db.add_index("Blocked Domain", ["enabled"])
	frappe.db.add_index("Blocked Domain", ["match_mode"])
	frappe.db.add_unique("Blocked Domain", ["parent_domain", "blocked_name"])
