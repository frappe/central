# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from central.deploy.github import GitHubDeployApp


class DeployApp(Document):
	"""One repository and branch a team deploys. A push to that branch deploys it."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		branch: DF.Data
		installation: DF.Link
		region: DF.Link | None
		repository: DF.Data
		repository_id: DF.Data
		status: DF.Literal["Active", "Disabled"]
		team: DF.Link
		virtual_machine: DF.Link | None
	# end: auto-generated types

	@staticmethod
	def add(team: str, repository: str, branch: str | None = None) -> DeployApp:
		"""Deploy `repository` (owner/name) from `branch`, or from its default branch when none is given."""
		app = GitHubDeployApp()
		installation, found = find_repository(app, team, repository)
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


def find_repository(app: GitHubDeployApp, team: str, repository: str) -> tuple[Document, dict]:
	"""The team's active installation that can access `repository`, and the repository as GitHub lists it."""
	names = frappe.get_all(
		"GitHub Deploy App Installation", filters={"team": team, "status": "Active"}, pluck="name"
	)
	for name in names:
		installation = frappe.get_doc("GitHub Deploy App Installation", name)
		for found in app.get_installation_repositories(installation.installation_id):
			if found["full_name"].lower() == repository.lower():
				return installation, found

	frappe.throw(
		_("Install the GitHub App on {0} and connect it to this team first.").format(repository),
		frappe.DoesNotExistError,
	)


def on_doctype_update() -> None:
	frappe.db.add_unique("Deploy App", ["team", "repository_id", "branch"])
	frappe.db.add_index("Deploy App", ["installation", "repository_id", "branch"])
