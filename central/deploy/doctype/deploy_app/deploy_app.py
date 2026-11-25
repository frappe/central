# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import hmac
import re

import frappe
from frappe import _
from frappe.model.document import Document

from central.infrastructure.doctype.blocked_domain.blocked_domain import BlockedDomain
from central.infrastructure.doctype.github_installation.github_installation import GitHubInstallation
from central.infrastructure.doctype.region.atlas_connection import is_auto_routed_label
from central.infrastructure.doctype.region.region import Region
from central.integrations.github import GitHubApp

DOMAIN_SUFFIX_LENGTH = 6
DOMAIN_ATTEMPTS = 5
MAX_LABEL_LENGTH = 63


class DeployApp(Document):
	"""One repository and branch a team deploys. A push to that branch deploys it."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		agent_token: DF.Password | None
		branch: DF.Data
		domain: DF.Data | None
		installation: DF.Link
		region: DF.Link | None
		repository: DF.Data
		repository_id: DF.Data
		status: DF.Literal["Active", "Disabled"]
		team: DF.Link
		virtual_machine: DF.Link | None
	# end: auto-generated types

	def before_insert(self):
		self.agent_token = frappe.generate_hash(length=32)

	@staticmethod
	def get_for_agent(credential: str) -> DeployApp:
		"""The app whose deploy agent sent `credential`, written `<app>:<token>`."""
		name, _separator, token = credential.partition(":")
		if name and token and frappe.db.exists("Deploy App", name):
			app: DeployApp = frappe.get_doc("Deploy App", name)
			expected = app.get_password("agent_token", raise_exception=False)
			if expected and hmac.compare_digest(expected, token):
				return app

		frappe.throw(_("This deploy agent token is not valid."), frappe.AuthenticationError)

	@staticmethod
	def validate_region(team: str, repository: str, branch: str | None, region: str) -> None:
		"""An app's VM lives in its region's Atlas, so an app that has one cannot move to another region.
		Without a branch, the default branch is unknown until GitHub returns, so `add` checks it then."""
		if not branch:
			return
		current = frappe.db.get_value(
			"Deploy App",
			{"team": team, "repository": repository, "branch": branch, "virtual_machine": ["is", "set"]},
			"region",
		)
		if current and current != region:
			throw_region_change(repository, current)

	@staticmethod
	def add(
		installation: GitHubInstallation, found: dict, region: str, branch: str | None = None
	) -> DeployApp:
		"""Deploy a repository the installation lists in `region`, from `branch` or else its default branch.
		The caller has checked that the user adding it is admin on the repository."""
		app = GitHubApp()
		team = installation.team
		branch = branch or found["default_branch"]
		if not app.has_branch(
			installation.installation_id, found["repository_id"], found["full_name"], branch
		):
			frappe.throw(_("Branch {0} does not exist in {1}.").format(branch, found["full_name"]))

		name = frappe.db.get_value(
			"Deploy App",
			{"team": team, "repository_id": found["repository_id"], "branch": branch},
			for_update=True,
		)
		doc = frappe.get_doc("Deploy App", name) if name else frappe.new_doc("Deploy App")
		# Checked again here, since the repository may have been renamed while the user was on GitHub.
		if doc.virtual_machine and doc.region != region:
			throw_region_change(found["full_name"], doc.region)
		# The domain lives under its region's zone; an app without a VM has no route yet to move.
		if not doc.domain or doc.region != region:
			doc.domain = get_new_domain(found["full_name"], region)
		doc.update(
			{
				"team": team,
				"installation": installation.name,
				"repository": found["full_name"],
				"repository_id": found["repository_id"],
				"branch": branch,
				"region": region,
				"status": "Active",
			}
		)
		# Central saves the app for a team; only System Manager has Desk access.
		doc.save(ignore_permissions=True)
		return doc

	def get_installation_id(self) -> str:
		return GitHubInstallation.get_installation_id(self.installation)

	@staticmethod
	def get_for_push(installation_id: str, repository_id: str, branch: str) -> list[str]:
		"""The active apps a push to `branch` deploys. Several teams, or none, can deploy one push."""
		installations = frappe.get_all(
			"GitHub Installation",
			filters={"installation_id": installation_id, "status": "Active"},
			pluck="name",
		)
		if not installations:
			return []

		return frappe.get_all(
			"Deploy App",
			filters={
				"installation": ["in", installations],
				"repository_id": repository_id,
				"branch": branch,
				"status": "Active",
			},
			pluck="name",
		)

	@staticmethod
	def disable_for_server(server: str) -> None:
		"""Stop deploying the apps of a terminated server, so a push no longer queues a deploy for it. The VM and
		domain are cleared, so connecting the app again gets a new VM and a new URL."""
		frappe.db.set_value(
			"Deploy App",
			{"virtual_machine": server, "status": "Active"},
			{"status": "Disabled", "virtual_machine": None, "domain": None},
		)


def on_doctype_update() -> None:
	frappe.db.add_unique("Deploy App", ["team", "repository_id", "branch"])
	frappe.db.add_index("Deploy App", ["installation", "repository_id", "branch"])


def throw_region_change(repository: str, region: str) -> None:
	frappe.throw(_("{0} already runs in {1}. Its region cannot change.").format(repository, region))


def get_new_domain(repository: str, region: str) -> str:
	"""`<repository name>-<6 random characters>` under the region's zone, unused and not reserved."""
	name = re.sub(r"[^a-z0-9]+", "-", repository.rpartition("/")[2].lower()).strip("-")
	name = name[: MAX_LABEL_LENGTH - DOMAIN_SUFFIX_LENGTH - 1].strip("-")
	# The proxy routes `site-*` and `*-vm-*` labels from the label itself, so they cannot be mapped.
	if not name or is_auto_routed_label(f"{name}-"):
		name = "app"

	zone = Region.get_zone(region)
	for _attempt in range(DOMAIN_ATTEMPTS):
		domain = f"{name}-{frappe.generate_hash(length=DOMAIN_SUFFIX_LENGTH)}.{zone}"
		if not (
			BlockedDomain.is_blocked(domain)
			or frappe.db.exists("Site Domain", domain)
			or frappe.db.exists("Deploy App", {"domain": domain})
		):
			return domain
	frappe.throw(_("Could not find a free domain for {0}. Try again.").format(repository))
