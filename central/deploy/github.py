import urllib.parse

import frappe
import requests
from frappe import _

from central.integrations.github import API_HEADERS, API_URL, TIMEOUT, GitHubApp, GitHubError

# A deploy config is a few lines; anything larger is refused before it is parsed.
MAX_FILE_BYTES = 64 * 1024
# The name GitHub shows the deploy under on each commit.
COMMIT_STATUS_CONTEXT = "Deploy"
# GitHub refuses a longer status description.
MAX_STATUS_DESCRIPTION = 140


class GitHubDeployApp(GitHubApp):
	"""The App push-to-deploy installs on user repositories, kept apart from Pilot's read-only App."""

	settings_prefix = "github_deploy_"
	callback_method = "central.deploy.api.oauth_callback"

	def get_file(
		self, installation_id: str, repository_id: str, full_name: str, path: str, ref: str
	) -> str | None:
		"""The text of `path` at `ref`, or None when the repository has no such file."""
		token = self.create_installation_token(installation_id, repository_id)["token"]
		url = f"{API_URL}/repos/{full_name}/contents/{urllib.parse.quote(path)}"
		headers = {
			**API_HEADERS,
			"Accept": "application/vnd.github.raw+json",
			"Authorization": f"Bearer {token}",
		}
		try:
			response = requests.get(url, headers=headers, params={"ref": ref}, timeout=TIMEOUT)
		except requests.RequestException as error:
			frappe.throw(_("GitHub could not be reached: {0}").format(str(error)), GitHubError)

		if response.status_code == 404:
			return None
		if not response.ok:
			frappe.throw(
				_("GitHub returned HTTP {0}: {1}").format(response.status_code, response.text[:200]),
				GitHubError,
			)
		if len(response.content) > MAX_FILE_BYTES:
			frappe.throw(_("{0} is larger than {1} bytes.").format(path, MAX_FILE_BYTES))
		return response.content.decode()

	def list_root(self, installation_id: str, repository_id: str, full_name: str, ref: str) -> list[dict]:
		"""The entries at the root of the repository at `ref`, each with its exact `name` and `type`."""
		token = self.create_installation_token(installation_id, repository_id)["token"]
		url = f"{API_URL}/repos/{full_name}/contents?{urllib.parse.urlencode({'ref': ref})}"
		return self._request("GET", url, token=token)

	def set_commit_status(
		self,
		installation_id: str,
		repository_id: str,
		full_name: str,
		commit: str,
		state: str,
		description: str,
		target_url: str | None = None,
	) -> None:
		"""Show the deploy's `state` (pending, success, failure or error) on `commit`."""
		token = self.create_installation_token(installation_id, repository_id, {"statuses": "write"})["token"]
		payload = {
			"state": state,
			"description": description[:MAX_STATUS_DESCRIPTION],
			"context": COMMIT_STATUS_CONTEXT,
			"target_url": target_url,
		}
		self._request("POST", f"{API_URL}/repos/{full_name}/statuses/{commit}", token=token, json=payload)
