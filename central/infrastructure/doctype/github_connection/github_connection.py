# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import base64
import hashlib
import json
import secrets

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.password import decrypt, encrypt

from central.iam import can
from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.integrations.github import GitHubApp


class GitHubRepositoryNotGranted(frappe.PermissionError):
	"""The Pilot has no active grant for this repository."""


class GitHubConnection(Document):
	"""A Pilot's grant to read selected repositories of one GitHub App installation."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from central.infrastructure.doctype.github_connection_repository.github_connection_repository import (
			GitHubConnectionRepository,
		)

		account: DF.Data | None
		account_type: DF.Literal["User", "Organization"]
		installation_id: DF.Data
		pilot_credential: DF.Link
		repositories: DF.Table[GitHubConnectionRepository]
		server: DF.Link | None
		status: DF.Literal["Active", "Disabled"]
		team: DF.Link
		version: DF.Int
	# end: auto-generated types

	@staticmethod
	def grant(credential: PilotCredential, installation: dict, repositories: list[dict]) -> GitHubConnection:
		"""Save the repositories one installation grants to a Pilot, replacing an earlier grant."""
		name = frappe.db.get_value(
			"GitHub Connection",
			{"pilot_credential": credential.name, "installation_id": installation["installation_id"]},
			for_update=True,
		)
		connection = (
			frappe.get_doc("GitHub Connection", name) if name else frappe.new_doc("GitHub Connection")
		)
		connection.update(
			{
				"team": credential.team,
				"server": credential.server,
				"pilot_credential": credential.name,
				"installation_id": installation["installation_id"],
				"account": installation["account"],
				"account_type": installation["account_type"],
				"status": "Active",
				"version": (connection.version or 0) + 1,
			}
		)
		connection.set(
			"repositories",
			[
				{"repository_id": repository["repository_id"], "full_name": repository["full_name"]}
				for repository in repositories
			],
		)
		# Central saves the grant for a Pilot; no Desk user owns it.
		connection.save(ignore_permissions=True)
		return connection

	@staticmethod
	def revoke(credential: PilotCredential, installation_id: str) -> None:
		"""Remove the grant of one installation from a Pilot."""
		name = frappe.db.get_value(
			"GitHub Connection",
			{"pilot_credential": credential.name, "installation_id": installation_id, "status": "Active"},
			for_update=True,
		)
		if name:
			frappe.get_doc("GitHub Connection", name).disable()

	@staticmethod
	def get_active(credential: PilotCredential) -> list[GitHubConnection]:
		names = frappe.get_all(
			"GitHub Connection",
			filters={"pilot_credential": credential.name, "status": "Active"},
			pluck="name",
			order_by="creation asc",
		)
		return [frappe.get_doc("GitHub Connection", name) for name in names]

	@staticmethod
	def find_repository(credential: PilotCredential, full_name: str) -> tuple[GitHubConnection, str]:
		"""The active connection that grants `full_name` to this Pilot, and the repository ID."""
		for connection in GitHubConnection.get_active(credential):
			for repository in connection.repositories:
				if repository.full_name.lower() == full_name.lower():
					return connection, repository.repository_id

		frappe.throw(
			_("Repository {0} is not granted to this server.").format(full_name), GitHubRepositoryNotGranted
		)

	def is_current(self, version: int) -> bool:
		"""Whether the grant is still active and unchanged since `version` was read."""
		status, current_version = frappe.db.get_value("GitHub Connection", self.name, ["status", "version"])
		return status == "Active" and current_version == version

	def disable(self) -> None:
		self.status = "Disabled"
		self.version += 1
		# The Pilot or a GitHub webhook disables the grant; no Desk user owns it.
		self.save(ignore_permissions=True)

	@staticmethod
	def disable_all() -> None:
		"""Disable every grant. Installations of a replaced GitHub App do not work with the new App."""
		for name in frappe.get_all("GitHub Connection", filters={"status": "Active"}, pluck="name"):
			frappe.get_doc("GitHub Connection", name, for_update=True).disable()

	@staticmethod
	def disable_installation(installation_id: str) -> None:
		for connection in GitHubConnection._lock_active(installation_id):
			connection.disable()

	@staticmethod
	def remove_repositories(installation_id: str, repository_ids: set[str]) -> None:
		for connection in GitHubConnection._lock_active(installation_id):
			kept = [row for row in connection.repositories if row.repository_id not in repository_ids]
			if len(kept) < len(connection.repositories):
				connection.set("repositories", kept)
				connection.version += 1
				# A GitHub webhook narrows the grant; no Desk user owns it.
				connection.save(ignore_permissions=True)

	@staticmethod
	def rename_repository(installation_id: str, repository_id: str, full_name: str) -> None:
		for connection in GitHubConnection._lock_active(installation_id):
			renamed = [row for row in connection.repositories if row.repository_id == repository_id]
			for row in renamed:
				row.full_name = full_name
			if renamed:
				# A GitHub webhook renames the repository; no Desk user owns the grant.
				connection.save(ignore_permissions=True)

	@staticmethod
	def _lock_active(installation_id: str) -> list[GitHubConnection]:
		names = frappe.get_all(
			"GitHub Connection",
			filters={"installation_id": installation_id, "status": "Active"},
			pluck="name",
		)
		return [frappe.get_doc("GitHub Connection", name, for_update=True) for name in names]


ATTEMPT_TTL_SECONDS = 60 * 60
# The state and return URL outlive the attempt, so an expired link can still send the user back.
LINK_TTL_SECONDS = 24 * 60 * 60


class GitHubConnectionAttempt:
	"""A Pilot's request to connect GitHub, kept in Redis. The first user who opens it owns it."""

	def __init__(self, attempt_id: str, data: dict) -> None:
		self.attempt_id = attempt_id
		self.data = data

	@classmethod
	def start(cls, credential: PilotCredential, return_url: str) -> GitHubConnectionAttempt:
		attempt = cls(
			secrets.token_urlsafe(24),
			{
				"pilot_credential": credential.name,
				"state": secrets.token_urlsafe(24),
				"code_verifier": secrets.token_urlsafe(48),
			},
		)
		attempt.save()
		frappe.cache.set_value(
			cls._state_key(attempt.state), attempt.attempt_id, expires_in_sec=LINK_TTL_SECONDS
		)
		frappe.cache.set_value(
			cls._return_key(attempt.attempt_id), return_url, expires_in_sec=LINK_TTL_SECONDS
		)
		return attempt

	@classmethod
	def find(cls, attempt_id: str) -> GitHubConnectionAttempt | None:
		data = frappe.cache.get_value(cls._key(attempt_id))
		return cls(attempt_id, json.loads(data)) if data else None

	@classmethod
	def load(cls, attempt_id: str) -> GitHubConnectionAttempt:
		attempt = cls.find(attempt_id)
		if not attempt:
			frappe.throw(
				_("This link has expired. Open Git settings on your server and connect GitHub again."),
				frappe.DoesNotExistError,
			)
		return attempt

	@classmethod
	def find_attempt_id(cls, state: str) -> str | None:
		return frappe.cache.get_value(cls._state_key(state))

	@classmethod
	def find_return_url(cls, attempt_id: str) -> str | None:
		return frappe.cache.get_value(cls._return_key(attempt_id))

	@property
	def credential(self) -> PilotCredential:
		credential = frappe.get_doc("Pilot Credential", self.data["pilot_credential"])
		if credential.status != "Active":
			frappe.throw(_("This server can no longer connect GitHub."), frappe.PermissionError)
		return credential

	@property
	def state(self) -> str:
		return self.data["state"]

	@property
	def code_challenge(self) -> str:
		digest = hashlib.sha256(self.data["code_verifier"].encode()).digest()
		return base64.urlsafe_b64encode(digest).decode().rstrip("=")

	@property
	def code_verifier(self) -> str:
		return self.data["code_verifier"]

	@property
	def user(self) -> str | None:
		# nosemgrep: frappe-cache-breaks-multitenancy -- make_key adds the site prefix.
		user = frappe.cache.get(frappe.cache.make_key(self._user_key(self.attempt_id)))
		return user.decode() if user else None

	@property
	def user_token(self) -> str | None:
		return decrypt(self.data["user_token"]) if self.data.get("user_token") else None

	def require_user_token(self) -> str:
		if not (user_token := self.user_token):
			frappe.throw(_("Authorize with GitHub first."), frappe.PermissionError)
		return user_token

	def bind(self, user: str) -> PilotCredential:
		"""Bind the attempt to the first user with console access to the server."""
		credential = self.credential
		if not can(user, credential.team, "server:console", server=credential.server):
			frappe.throw(
				_("You can't connect GitHub to this server. Ask a team admin to review your access."),
				frappe.PermissionError,
			)
		# A credential with no linked server has no machine to protect yet.
		if credential.server:
			frappe.get_doc("Virtual Machine", credential.server).require_server_access(user)

		# SET NX lets only one user claim the attempt, even when two users open it at once.
		# nosemgrep: frappe-cache-breaks-multitenancy -- make_key adds the site prefix.
		frappe.cache.set(
			frappe.cache.make_key(self._user_key(self.attempt_id)), user, nx=True, ex=LINK_TTL_SECONDS
		)
		if self.user != user:
			frappe.throw(
				_("Another user already opened this GitHub connection link."), frappe.PermissionError
			)

		# Activity keeps the attempt alive during a long trip through GitHub.
		frappe.cache.expire_key(self._key(self.attempt_id), ATTEMPT_TTL_SECONDS)
		return credential

	def set_user_token(self, token: str) -> None:
		self.data["user_token"] = encrypt(token)
		self.save()

	def complete(self, grants: dict[str, list[str]]) -> None:
		"""Grant the selected repositories of each installation. An installation sent empty loses its grant."""
		credential = self.credential
		app = GitHubApp()
		user_token = self.require_user_token()
		installations = {item["installation_id"]: item for item in app.get_user_installations(user_token)}
		if not set(grants) <= set(installations):
			frappe.throw(_("You can't access this GitHub installation."), frappe.PermissionError)

		# Check with GitHub before saving, so no row lock is held during a GitHub call.
		selections = {
			installation_id: self._get_admin_repositories(app, user_token, installation_id, repository_ids)
			for installation_id, repository_ids in grants.items()
		}
		for installation_id, repositories in selections.items():
			if repositories:
				GitHubConnection.grant(credential, installations[installation_id], repositories)
			else:
				GitHubConnection.revoke(credential, installation_id)

		self.finish()

	@staticmethod
	def _get_admin_repositories(
		app: GitHubApp, user_token: str, installation_id: str, repository_ids: list[str]
	) -> list[dict]:
		"""The selected repositories of one installation, each administered by the user."""
		if not repository_ids:
			return []

		repositories = {
			repository["repository_id"]: repository
			for repository in app.get_user_repositories(user_token, installation_id)
			if repository["is_admin"]
		}
		if any(repository_id not in repositories for repository_id in repository_ids):
			frappe.throw(_("Select repositories where you are an administrator."), frappe.PermissionError)
		return [repositories[repository_id] for repository_id in repository_ids]

	def finish(self) -> None:
		frappe.cache.delete_value(self._key(self.attempt_id))

	def save(self) -> None:
		frappe.cache.set_value(
			self._key(self.attempt_id), json.dumps(self.data), expires_in_sec=ATTEMPT_TTL_SECONDS
		)

	@staticmethod
	def _key(attempt_id: str) -> str:
		return f"github:connection-attempt:{attempt_id}"

	@staticmethod
	def _state_key(state: str) -> str:
		return f"github:connection-state:{state}"

	@staticmethod
	def _return_key(attempt_id: str) -> str:
		return f"github:connection-return:{attempt_id}"

	@staticmethod
	def _user_key(attempt_id: str) -> str:
		return f"github:connection-user:{attempt_id}"


def on_doctype_update() -> None:
	frappe.db.add_unique("GitHub Connection", ["pilot_credential", "installation_id"])
