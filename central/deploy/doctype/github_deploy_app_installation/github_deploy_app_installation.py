# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import json
import secrets

import frappe
from frappe import _
from frappe.model.document import Document

from central.deploy.doctype.deploy_app.deploy_app import DeployApp
from central.deploy.github import GitHubDeployApp
from central.iam import can

STATE_TTL_SECONDS = 60 * 60


class GitHubDeployAppInstallation(Document):
	"""A team's access to one installation of the push-to-deploy GitHub App."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		account: DF.Data | None
		account_type: DF.Literal["User", "Organization"]
		installation_id: DF.Data
		status: DF.Literal["Active", "Disabled"]
		team: DF.Link
	# end: auto-generated types

	@staticmethod
	def start(team: str, user: str, repository: str, region: str, branch: str | None = None) -> str:
		"""A new attempt to deploy `repository` (owner/name) for `team` in `region`. Its state lets only `user` finish it."""
		require_deploy_access(user, team)
		if not frappe.db.exists("Region", region):
			frappe.throw(_("Region {0} does not exist.").format(region), frappe.DoesNotExistError)
		state = secrets.token_urlsafe(24)
		save_attempt(
			state, {"team": team, "user": user, "repository": repository, "region": region, "branch": branch}
		)
		return state

	@staticmethod
	def verify(state: str, code: str, installation_id: str, user: str) -> None:
		"""Keep the installation GitHub returned to, once the user's token proves they can access it and
		are admin on the repository. Only Redis is written: GitHub returns with a GET, which Frappe
		rolls back, so `complete` saves it."""
		attempt = load_attempt(state, user)
		require_deploy_access(user, attempt["team"])

		# The installation ID in the callback URL is user input; GitHub's own list is the proof.
		app = GitHubDeployApp()
		user_token = app.exchange_code(code)
		installations = app.get_user_installations(user_token)
		installation = next(
			(item for item in installations if item["installation_id"] == installation_id), None
		)
		if not installation:
			frappe.throw(_("You can't access this GitHub installation."), frappe.PermissionError)

		# The user's own list, not the installation's: it has only the repositories this user can access.
		repositories = app.get_user_repositories(user_token, installation_id)
		repository = next(
			(item for item in repositories if item["full_name"].lower() == attempt["repository"].lower()),
			None,
		)
		if not repository:
			frappe.throw(
				_("You can't access {0} through this installation.").format(attempt["repository"]),
				frappe.PermissionError,
			)
		if not repository["is_admin"]:
			frappe.throw(
				_("Only an admin of {0} can deploy it.").format(repository["full_name"]),
				frappe.PermissionError,
			)

		attempt["installation"] = installation
		attempt["found_repository"] = repository
		save_attempt(state, attempt)

	@staticmethod
	def is_verified(state: str, user: str) -> bool:
		"""Whether GitHub returned to the callback for this attempt yet."""
		return "installation" in load_attempt(state, user)

	@staticmethod
	def complete(state: str, user: str) -> DeployApp:
		"""Link the verified installation to the attempt's team and deploy its repository. The attempt works only once."""
		attempt = load_attempt(state, user)
		if not attempt.get("installation"):
			frappe.throw(_("Install the GitHub App first."), frappe.PermissionError)
		require_deploy_access(user, attempt["team"])

		frappe.cache.delete_value(state_key(state))
		installation = GitHubDeployAppInstallation.link(attempt["team"], attempt["installation"])
		return DeployApp.add(installation, attempt["found_repository"], attempt["region"], attempt["branch"])

	@staticmethod
	def link(team: str, installation: dict) -> GitHubDeployAppInstallation:
		name = frappe.db.get_value(
			"GitHub Deploy App Installation",
			{"team": team, "installation_id": installation["installation_id"]},
			for_update=True,
		)
		doc = (
			frappe.get_doc("GitHub Deploy App Installation", name)
			if name
			else frappe.new_doc("GitHub Deploy App Installation")
		)
		doc.update(
			{
				"team": team,
				"installation_id": installation["installation_id"],
				"account": installation["account"],
				"account_type": installation["account_type"],
				"status": "Active",
			}
		)
		# The GitHub callback saves the link after its own checks; only System Manager has Desk access.
		doc.save(ignore_permissions=True)
		return doc


def require_deploy_access(user: str, team: str) -> None:
	if not can(user, team, "app:deploy"):
		frappe.throw(_("You can't connect GitHub to this team."), frappe.PermissionError)


def load_attempt(state: str, user: str) -> dict:
	# The callback updates the attempt in another process; set_value keeps a stale copy in this one.
	data = frappe.cache.get_value(state_key(state), use_local_cache=False)
	if not data:
		frappe.throw(_("This GitHub link has expired. Connect GitHub again."), frappe.DoesNotExistError)

	attempt = json.loads(data)
	if attempt["user"] != user:
		frappe.throw(_("Another user started this GitHub connection."), frappe.PermissionError)
	return attempt


def save_attempt(state: str, attempt: dict) -> None:
	frappe.cache.set_value(state_key(state), json.dumps(attempt), expires_in_sec=STATE_TTL_SECONDS)


def state_key(state: str) -> str:
	return f"github-deploy:install-state:{state}"


def on_doctype_update() -> None:
	frappe.db.add_unique("GitHub Deploy App Installation", ["team", "installation_id"])
	frappe.db.add_index("GitHub Deploy App Installation", ["installation_id", "status"])
