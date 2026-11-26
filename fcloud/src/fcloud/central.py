import json
import os

import httpx2

from fcloud.auth.credentials import ApiKeyCredential, Credential, get_credential
from fcloud.errors import CentralError, FcloudError
from fcloud.profiles import ProfileStore

TIMEOUT_SECONDS = 30


class Central:
	"""An authenticated connection to one Central site. Domain objects such as DeployApp make their calls through it."""

	def __init__(self, url: str, credential: Credential):
		self.url = url.rstrip("/")
		self.credential = credential
		self.client = httpx2.Client(base_url=self.url, timeout=TIMEOUT_SECONDS)

	@classmethod
	def connect(cls, profile_name: str | None = None) -> "Central":
		"""Connect with FCLOUD_URL and its API key when set, else with the named or default profile."""
		if "FCLOUD_URL" in os.environ:
			return cls(os.environ["FCLOUD_URL"], get_environment_credential())

		profile = ProfileStore().get(profile_name)
		return cls(profile.url, get_credential(profile))

	def request(self, method: str, path: str, params: dict | None = None, body: dict | None = None):
		"""Send a request and return Frappe's `message` or `data`. Retry once with a renewed credential."""
		response = self.send(method, path, params, body)
		# Frappe treats a rejected bearer token as Guest, so a revoked or expired one returns 401 or 403.
		if response.status_code in (401, 403) and self.credential.refresh():
			response = self.send(method, path, params, body)

		if response.is_error:
			raise get_error(response)
		payload = response.json()
		return payload.get("message", payload.get("data"))

	def send(self, method: str, path: str, params: dict | None, body: dict | None) -> httpx2.Response:
		headers = {"Authorization": self.credential.get_authorization_header(), "Accept": "application/json"}
		return self.client.request(method, path, params=params, json=body, headers=headers)

	def call(self, method: str, **arguments):
		"""POST to a whitelisted method."""
		return self.request("POST", f"/api/method/{method}", body=arguments)

	def get(self, method: str, **arguments):
		"""GET from a whitelisted method."""
		return self.request("GET", f"/api/method/{method}", params=arguments)

	def get_list(self, doctype: str, filters: list, fields: list[str], limit: int = 20) -> list[dict]:
		params = {
			"filters": json.dumps(filters),
			"fields": json.dumps(fields),
			"order_by": "creation desc",
			"limit_page_length": limit,
		}
		return self.request("GET", f"/api/resource/{doctype}", params=params)

	def get_user(self) -> str:
		return self.get("frappe.auth.get_logged_user")

	def get_teams(self) -> list[dict]:
		"""The active teams of the signed-in user."""
		teams = self.get("central.api.identity.my_teams")
		return [team for team in teams if team["status"] == "Active"]


def get_environment_credential() -> ApiKeyCredential:
	try:
		return ApiKeyCredential(os.environ["FCLOUD_API_KEY"], os.environ["FCLOUD_API_SECRET"])
	except KeyError as error:
		raise FcloudError(f"Set {error.args[0]} with FCLOUD_URL.")


def get_error(response: httpx2.Response) -> CentralError:
	"""Frappe's readable message from an error response."""
	try:
		body = response.json()
	except ValueError:
		return CentralError(response.reason_phrase, response.status_code)

	messages = [
		json.loads(item).get("message", "") for item in json.loads(body.get("_server_messages", "[]"))
	]
	message = "; ".join(messages) or body.get("exception") or response.reason_phrase
	return CentralError(message, response.status_code, body.get("exc_type", ""))
