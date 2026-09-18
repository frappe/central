from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import frappe
from frappe.model.document import Document

IMAGE_SITE_NAME = "site.local"


class Site(Document):
	"""The site a Pilot image already carries, on the machine that runs it.

	Central builds no site. Cargo bakes one bench and one site into every image, and the
	image answers for it on a `site-*` hostname alias, so a machine with an enrolled
	Pilot always has exactly one site, at an address its own mesh address decides.

	This record therefore holds only what belongs to the site: which machine it is, and
	the name that machine knows it by. Its address is its name and its state is the
	machine's, so neither is copied here, where the two could drift apart."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		asset: DF.Link
		claimed_at: DF.Datetime | None
		rename_task: DF.Data | None
		site_name: DF.Data
		subdomain: DF.Data | None
		team: DF.Link
	# end: auto-generated types

	@property
	def rename_target(self) -> str:
		"""The hostname the customer chose, which the bench is renamed onto.

		It is only ever a rename target. Nothing reads it and nothing is sent to it, because
		it does not serve until the rename lands. Their name and ours share the regional
		zone, and the site's own name already carries it, so this is built from ours."""
		_, zone = self.name.split(".", 1)
		return f"{self.subdomain}.{zone}"

	@property
	def url(self) -> str:
		"""The site's address: the one the region derives from the machine itself.

		It answers before the customer has chosen a name and after the bench is renamed
		onto theirs, so it is what every reader, probe and sign-in uses. The proxy
		terminates TLS in front of it."""
		return f"https://{self.name}"

	@property
	def status(self) -> str | None:
		"""A site has no lifecycle of its own, so its machine's state is its state."""
		return frappe.db.get_value("Asset", self.asset, "status")

	@classmethod
	def ensure_for(cls, asset: str) -> None:
		"""Write down the site of a machine that has reached a routable address.

		A region reports on a machine repeatedly and this runs on every report, because
		the address arrives on one of them and nothing says which. It writes once: a
		machine that already has a site, runs no Pilot, or has no address yet is left
		alone."""
		if frappe.db.exists("Site", {"asset": asset}):
			return

		machine = frappe.db.get_value("Asset", asset, ["team", "cluster", "ipv6_address"], as_dict=True)
		if not machine or not machine.ipv6_address:
			return
		if not frappe.db.exists("Pilot Credential", {"asset": asset, "status": "Active"}):
			return

		host = frappe.get_cached_doc("Atlas Instance", machine.cluster).get_vm_site_host(machine.ipv6_address)
		if not host:
			return

		# The verified region authorizes this record, the same way it authorizes the machine's.
		frappe.get_doc(
			{
				"doctype": "Site",
				"site_name": host,
				"subdomain": frappe.db.get_value(
					"Resource Action", {"asset": asset, "action": "create"}, "subdomain"
				),
				"team": machine.team,
				"asset": asset,
			}
		).insert(ignore_permissions=True)

	def mark_claimed(self) -> None:
		"""Record the first successful login handoff and schedule the optional rename."""
		if not self.claimed_at:
			self.db_set("claimed_at", frappe.utils.now_datetime())

		self.enqueue_subdomain_rename()

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
		"""Move the bench onto the name the customer chose, once and never again.

		Pilot renames on its own task, so this returns as soon as the rename is accepted
		rather than finished. Both hostnames keep serving throughout, which is what lets
		the customer be signed in at our address while theirs is still coming up."""
		from central.integrations.pilot import rename_site

		if not self.subdomain or self.rename_task:
			return

		task = rename_site(self.asset, IMAGE_SITE_NAME, self.rename_target)
		self.db_set("rename_task", task.get("task_id"))

	def get_login_url(self) -> str | None:
		"""A one-click Administrator session, on the address the customer can reach.

		Pilot mints against the stable image alias. The public name is Central's, so putting
		the session onto that address is Central's to do."""
		from central.integrations.pilot import fetch_site_login_url

		gateway, audience = self.get_pilot_access()
		if not gateway or not audience:
			return None

		minted = fetch_site_login_url(gateway, audience, IMAGE_SITE_NAME)
		return on_host(minted, self.name) if minted else None

	def get_pilot_access(self) -> tuple[str | None, str | None]:
		"""The running machine's gateway and the audience its Pilot verifies tokens against."""
		gateway = frappe.db.get_value(
			"Asset", {"name": self.asset, "team": self.team, "status": "Running"}, "gateway_url"
		)
		audience = frappe.db.get_value(
			"Pilot Credential", {"asset": self.asset, "team": self.team, "status": "Active"}, "audience_id"
		)
		return (gateway.rstrip("/") if gateway else None), audience


def on_host(url: str, host: str) -> str:
	"""The same request on another host. The scheme is always https, because the public
	name exists only behind the regional proxy, which terminates TLS."""
	minted = urlsplit(url)
	return urlunsplit(("https", host, minted.path, minted.query, minted.fragment))


def on_doctype_update():
	# The fleet reads a team's sites, then drops the machine each one already stands for.
	frappe.db.add_index("Site", ["team", "asset"])
