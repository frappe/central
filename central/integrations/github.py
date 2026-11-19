from __future__ import annotations

import hashlib
import hmac
import time
import urllib.parse

import frappe
import jwt
import requests
from frappe import _

from central.sso import central_url

API_URL = "https://api.github.com"
WEB_URL = "https://github.com"
API_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
TIMEOUT = (5, 20)
PAGE_SIZE = 100


class GitHubError(frappe.ValidationError):
	"""GitHub refused a call or could not be reached."""


class GitHubApp:
	"""Calls to GitHub as the App or as a signed-in GitHub user. The App secrets never leave Central."""

	def __init__(self) -> None:
		if not self.is_configured():
			frappe.throw(_("The GitHub App is not configured in Central Settings."), GitHubError)

		self.settings = frappe.get_cached_doc("Central Settings")
		self.app_id = self.settings.github_app_id
		self.client_id = self.settings.github_client_id
		self.slug = self.settings.github_app_slug

	@staticmethod
	def is_configured() -> bool:
		settings = frappe.get_cached_doc("Central Settings")
		return bool(settings.github_app_id and settings.github_client_id and settings.github_app_slug)

	def get_authorize_url(self, state: str, code_challenge: str) -> str:
		query = {
			"client_id": self.client_id,
			"state": state,
			"code_challenge": code_challenge,
			"code_challenge_method": "S256",
			"redirect_uri": callback_url(),
		}
		return f"{WEB_URL}/login/oauth/authorize?{urllib.parse.urlencode(query)}"

	def get_install_url(self, state: str) -> str:
		return f"{WEB_URL}/apps/{self.slug}/installations/new?{urllib.parse.urlencode({'state': state})}"

	def exchange_code(self, code: str, code_verifier: str) -> str:
		"""The user access token for an OAuth code."""
		payload = {
			"client_id": self.client_id,
			"client_secret": self.settings.get_password("github_client_secret"),
			"code": code,
			"code_verifier": code_verifier,
			"redirect_uri": callback_url(),
		}
		body = self._request("POST", f"{WEB_URL}/login/oauth/access_token", json=payload)
		if not body.get("access_token"):
			frappe.throw(
				_("GitHub did not accept the authorization: {0}").format(body.get("error", "")), GitHubError
			)

		return body["access_token"]

	def get_user_installations(self, user_token: str) -> list[dict]:
		"""Installations of this App that the user can access."""
		return [
			{
				"installation_id": str(installation["id"]),
				"account": installation["account"]["login"],
				"account_type": installation["account"]["type"],
				"avatar_url": installation["account"].get("avatar_url", ""),
			}
			for installation in self._paginate(f"{API_URL}/user/installations", user_token, "installations")
			if installation.get("app_id") == int(self.app_id)
		]

	def get_user_repositories(self, user_token: str, installation_id: str) -> list[dict]:
		"""Repositories of one installation that the user can access, with their admin right."""
		url = f"{API_URL}/user/installations/{int(installation_id)}/repositories"
		return [
			repository_summary(repository) for repository in self._paginate(url, user_token, "repositories")
		]

	def get_installation_repositories(self, installation_id: str) -> list[dict]:
		token = self.create_installation_token(installation_id)["token"]
		url = f"{API_URL}/installation/repositories"
		return [repository_summary(repository) for repository in self._paginate(url, token, "repositories")]

	def create_installation_token(self, installation_id: str, repository_id: str | None = None) -> dict:
		"""An installation token, limited to one repository and `contents: read` when one is given."""
		payload = {}
		if repository_id:
			payload = {"repository_ids": [int(repository_id)], "permissions": {"contents": "read"}}

		body = self._request(
			"POST",
			f"{API_URL}/app/installations/{int(installation_id)}/access_tokens",
			token=self._app_jwt(),
			json=payload,
		)
		return {"token": body["token"], "expires_at": body["expires_at"]}

	def is_valid_webhook_signature(self, body: bytes, signature: str) -> bool:
		secret = self.settings.get_password("github_webhook_secret", raise_exception=False)
		if not secret:
			return False

		expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
		return hmac.compare_digest(expected, signature or "")

	def _app_jwt(self) -> str:
		now = int(time.time())
		# GitHub rejects an `iat` in the future, so it is set back for clock drift.
		claims = {"iat": now - 60, "exp": now + 540, "iss": self.client_id}
		return jwt.encode(claims, self.private_key, algorithm="RS256")

	@property
	def private_key(self) -> str:
		key = self.settings.get_password("github_private_key")
		# A Password input drops line breaks when a key is pasted by hand.
		if "\n" not in key.strip():
			header, _, rest = key.partition("KEY-----")
			body, _, footer = rest.rpartition("-----END")
			key = f"{header}KEY-----\n" + "\n".join(body.split()) + f"\n-----END{footer}"
		return key

	def _paginate(self, url: str, token: str, key: str) -> list[dict]:
		"""Every item of a paged GitHub list, read from `key` of each page."""
		items = []
		page = 1
		while True:
			body = self._request("GET", f"{url}?per_page={PAGE_SIZE}&page={page}", token=token)
			batch = body.get(key, [])
			items.extend(batch)
			if len(batch) < PAGE_SIZE:
				return items
			page += 1

	@staticmethod
	def _request(method: str, url: str, token: str | None = None, json: dict | None = None) -> dict:
		headers = dict(API_HEADERS)
		if token:
			headers["Authorization"] = f"Bearer {token}"

		try:
			response = requests.request(method, url, headers=headers, json=json, timeout=TIMEOUT)
		except requests.RequestException as error:
			frappe.throw(_("GitHub could not be reached: {0}").format(str(error)), GitHubError)

		if not response.ok:
			frappe.throw(
				_("GitHub returned HTTP {0}: {1}").format(response.status_code, response.text[:200]),
				GitHubError,
			)

		return response.json()


def callback_url() -> str:
	return f"{central_url()}/api/method/central.api.integrations.github.oauth_callback"


def repository_summary(repository: dict) -> dict:
	"""The same shape Pilot's own GitHub provider returns."""
	return {
		"repository_id": str(repository["id"]),
		"name": repository["name"],
		"full_name": repository["full_name"],
		"private": repository.get("private", False),
		"description": repository.get("description") or "",
		"default_branch": repository.get("default_branch") or "",
		"clone_url": repository.get("clone_url") or "",
		"is_admin": bool(repository.get("permissions", {}).get("admin")),
	}


def convert_manifest(code: str) -> dict:
	"""The new App's credentials for a one-time manifest code."""
	return GitHubApp._request("POST", f"{API_URL}/app-manifests/{code}/conversions")
