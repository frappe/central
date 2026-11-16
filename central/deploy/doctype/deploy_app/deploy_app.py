# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import hmac
from typing import TYPE_CHECKING

import frappe
from frappe import _
from frappe.model.document import Document

from central.deploy.github import GitHubDeployApp

if TYPE_CHECKING:
	from central.deploy.doctype.github_deploy_app_installation.github_deploy_app_installation import (
		GitHubDeployAppInstallation,
	)


class DeployApp(Document):
	"""One repository and branch a team deploys. A push to that branch deploys it."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		agent_token: DF.Password | None
		branch: DF.Data
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
	def add(installation: GitHubDeployAppInstallation, found: dict, branch: str | None = None) -> DeployApp:
		"""Deploy a repository the installation lists, from `branch` or else its default branch.
		The caller has checked that the user adding it is admin on the repository."""
		app = GitHubDeployApp()
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
		doc.update(
			{
				"team": team,
				"installation": installation.name,
				"repository": found["full_name"],
				"repository_id": found["repository_id"],
				"branch": branch,
				"status": "Active",
			}
		)
		# Central saves the app for a team; only System Manager has Desk access.
		doc.save(ignore_permissions=True)
		return doc

	@staticmethod
	def get_for_push(installation_id: str, repository_id: str, branch: str) -> list[str]:
		"""The active apps a push to `branch` deploys. Several teams, or none, can deploy one push."""
		installations = frappe.get_all(
			"GitHub Deploy App Installation",
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


def on_doctype_update() -> None:
	frappe.db.add_unique("Deploy App", ["team", "repository_id", "branch"])
	frappe.db.add_index("Deploy App", ["installation", "repository_id", "branch"])
