from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets

import frappe
from frappe import _
from frappe.utils.password import decrypt, encrypt

from central.deploy.doctype.deploy_app.deploy_app import DeployApp
from central.iam import can
from central.infrastructure.doctype.github_installation.github_installation import GitHubInstallation
from central.integrations.github import GitHubApp

STATE_TTL_SECONDS = 60 * 60
# A deploy writes its status on the commit, records a live deploy as a GitHub deployment, and starts from a push.
DEPLOY_PERMISSIONS, DEPLOY_EVENT = {"statuses": "write", "deployments": "write"}, "push"
# owner/name alone, or inside a github.com URL or SSH remote. GitHub owners are letters, digits and
# hyphens; repository names may also have dots and underscores.
REPOSITORY_PATTERN = re.compile(
	r"(?:(?:https?://)?(?:www\.)?github\.com/|git@github\.com:)?"
	r"(?P<owner_and_name>[A-Za-z0-9-]+/[A-Za-z0-9._-]+?)(?:\.git)?/?"
)


class DeployConnectionAttempt:
	"""A user's attempt to deploy one repository: GitHub sign-in, the installation that reaches the repository,
	then the Deploy App. It lives in Redis until it completes or expires."""

	@staticmethod
	def start(team: str, user: str, repository: str, region: str, branch: str | None = None) -> str:
		"""A new attempt to deploy `repository` (owner/name) for `team` in `region`. Its state lets only `user` finish it."""
		require_deploy_access(user, team)
		repository = to_owner_and_name(repository)
		if not frappe.db.exists("Region", region):
			frappe.throw(_("Region {0} does not exist.").format(region), frappe.DoesNotExistError)
		DeployApp.validate_region(team, repository, branch, region)
		state = secrets.token_urlsafe(24)
		save_attempt(
			state,
			{
				"team": team,
				"user": user,
				"repository": repository,
				"region": region,
				"branch": branch,
				"code_verifier": secrets.token_urlsafe(48),
			},
		)
		return state

	@staticmethod
	def has_attempt(state: str) -> bool:
		"""Whether `state` is a deploy attempt's, so the GitHub App's callback sends it here."""
		return frappe.cache.get_value(state_key(state)) is not None

	@staticmethod
	def get_sign_in_url(state: str, user: str) -> str:
		"""The GitHub sign-in that returns to the callback with a code for this attempt."""
		digest = hashlib.sha256(load_attempt(state, user)["code_verifier"].encode()).digest()
		challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
		return GitHubApp().get_authorize_url(state, challenge)

	@staticmethod
	def verify(state: str, code: str, installation_id: str | None, user: str) -> str | None:
		"""Trade GitHub's code for the user's token and look for the repository in their installations. A code
		from the sign-in has no installation; one from an install names it. Returns the GitHub page the user goes
		to next, or None once the repository is found. Only Redis is written: GitHub returns with a GET, which
		Frappe rolls back, so `complete` saves the link."""
		attempt = load_attempt(state, user)
		require_deploy_access(user, attempt["team"])
		# Only the sign-in sent a PKCE challenge; a code from an install has none.
		verifier = None if installation_id else attempt["code_verifier"]
		attempt["user_token"] = encrypt(GitHubApp().exchange_code(code, verifier))
		return DeployConnectionAttempt.find_repository(state, attempt, installation_id)

	@staticmethod
	def find_repository(state: str, attempt: dict, installation_id: str | None = None) -> str | None:
		"""Keep the installation through which the user reaches the attempt's repository as an admin. Returns the
		GitHub page the user goes to next: the install page, or the installation's settings to accept the
		deploy permissions. None means the installation can deploy the repository."""
		app = GitHubApp()
		user_token = decrypt(attempt["user_token"])
		# The installation ID in the callback URL is user input; GitHub's own list is the proof.
		installations = [
			item
			for item in app.get_user_installations(user_token)
			if not installation_id or item["installation_id"] == installation_id
		]
		if installation_id and not installations:
			frappe.throw(_("You can't access this GitHub installation."), frappe.PermissionError)

		# The user's own lists, not the installations': they have only the repositories this user can access.
		found = next(
			(
				(installation, repository)
				for installation in installations
				for repository in app.get_user_repositories(user_token, installation["installation_id"])
				if repository["full_name"].lower() == attempt["repository"].lower()
			),
			None,
		)
		if not found:
			if installation_id:
				frappe.throw(
					_("You can't access {0} through this installation.").format(attempt["repository"]),
					frappe.PermissionError,
				)
			save_attempt(state, attempt)
			return app.get_install_url(state)

		installation, repository = found
		if not repository["is_admin"]:
			frappe.throw(
				_("Only an admin of {0} can deploy it.").format(repository["full_name"]),
				frappe.PermissionError,
			)
		# An installation made before the App asked for these keeps its old permissions until an owner accepts.
		if not has_deploy_permissions(installation):
			attempt["unaccepted_account"] = installation["account"]
			save_attempt(state, attempt)
			return app.get_installation_settings_url(installation)

		attempt.pop("user_token")
		attempt.pop("unaccepted_account", None)
		attempt.update(installation=installation, found_repository=repository)
		save_attempt(state, attempt)
		return None

	@staticmethod
	def is_verified(state: str, user: str) -> bool:
		"""Whether GitHub returned to the callback for this attempt yet."""
		return "installation" in load_attempt(state, user)

	@staticmethod
	def complete(state: str, user: str) -> DeployApp:
		"""Link the verified installation to the attempt's team and deploy its repository. The attempt works only once."""
		attempt = load_attempt(state, user)
		require_deploy_access(user, attempt["team"])
		# GitHub sends no callback when a repository is added to an existing installation, so look again.
		if not attempt.get("installation") and attempt.get("user_token"):
			DeployConnectionAttempt.find_repository(state, attempt)
		if not attempt.get("installation") and attempt.get("unaccepted_account"):
			frappe.throw(
				_("Accept the GitHub App's new permissions on {0} first.").format(
					attempt["unaccepted_account"]
				),
				frappe.PermissionError,
			)
		if not attempt.get("installation"):
			frappe.throw(_("Install the GitHub App first."), frappe.PermissionError)

		frappe.cache.delete_value(state_key(state))
		installation = GitHubInstallation.link(attempt["team"], attempt["installation"])
		return DeployApp.add(installation, attempt["found_repository"], attempt["region"], attempt["branch"])


def has_deploy_permissions(installation: dict) -> bool:
	permissions = installation["permissions"]
	has_permissions = all(permissions.get(name) == level for name, level in DEPLOY_PERMISSIONS.items())
	return has_permissions and DEPLOY_EVENT in installation["events"]


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


def to_owner_and_name(repository: str) -> str:
	"""owner/name from owner/name itself, a github.com URL, or an SSH remote."""
	match = REPOSITORY_PATTERN.fullmatch(repository.strip())
	if not match:
		frappe.throw(
			_("Pass the repository as owner/name, such as frappe/erpnext, not {0}.").format(repository)
		)
	return match["owner_and_name"]
