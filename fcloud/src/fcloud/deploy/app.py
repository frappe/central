from dataclasses import dataclass

from fcloud.central import Central
from fcloud.errors import CentralError, FcloudError

API = "central.deploy.api"
# Central answers with these while the person is still installing or approving the GitHub App.
PENDING_GITHUB = ("Install the GitHub App first.", "Accept the GitHub App's new permissions")


class DeployApp:
	"""A repository branch connected to push-to-deploy."""

	def __init__(self, central: Central, fields: dict):
		self.central = central
		self.name: str = fields["name"]
		self.repository: str = fields["repository"]
		self.branch: str = fields["branch"]
		self.domain: str | None = fields.get("domain")
		self.region: str | None = fields.get("region")
		self.status: str | None = fields.get("status")

	@classmethod
	def find(cls, central: Central, repository: str, branch: str | None) -> "DeployApp":
		if not branch:
			raise FcloudError("Pass --branch with --repository.")

		apps = central.get_list(
			"Deploy App",
			[["repository", "=", repository], ["branch", "=", branch]],
			["name", "repository", "branch", "domain", "region"],
			limit=1,
		)
		if not apps:
			raise FcloudError(f"{repository}@{branch} is not connected. Run `fcloud launch` first.")
		return cls(central, apps[0])

	@classmethod
	def get_all(cls, central: Central, team: str) -> list["DeployApp"]:
		return [cls(central, fields) for fields in central.get(f"{API}.get_apps", team=team)]

	@property
	def url(self) -> str | None:
		return f"https://{self.domain}" if self.domain else None

	@property
	def label(self) -> str:
		return f"{self.repository}@{self.branch}"

	def get_deploys(self, limit: int = 20) -> list[dict]:
		"""The app's deploy requests, newest first."""
		return self.central.get_list(
			"Deploy Request",
			[["deploy_app", "=", self.name]],
			["name", "commit", "status", "creation", "error"],
			limit=limit,
		)

	def get_latest_deploy_name(self) -> str:
		deploys = self.get_deploys(limit=1)
		if not deploys:
			raise FcloudError("No deploys yet. Push to the branch to start one.")
		return deploys[0]["name"]

	def disable(self) -> None:
		self.central.call(f"{API}.disable_app", name=self.name)

	def get_secret_names(self) -> list[str]:
		return self.central.get(f"{API}.get_app_secrets", name=self.name)

	def update_secrets(
		self, secrets: dict[str, str] | None = None, unset: list[str] | None = None
	) -> list[str]:
		"""Set and remove secrets in one change. Return the secret names after it."""
		change = {"secrets": secrets} if secrets else {"unset": unset}
		return self.central.call(f"{API}.update_app_secrets", name=self.name, **change)


@dataclass
class RepositoryConnection:
	"""A repository being connected. The person signs in to GitHub in the browser, then Central creates the app."""

	central: Central
	sign_in_url: str
	state: str

	@classmethod
	def start(
		cls, central: Central, team: str, repository: str, region: str, branch: str | None
	) -> "RepositoryConnection":
		started = central.call(
			f"{API}.connect_repository", team=team, repository=repository, region=region, branch=branch
		)
		return cls(central, started["sign_in_url"], started["state"])

	def get_app(self) -> DeployApp | None:
		"""The connected app, or None while GitHub still waits for the person."""
		try:
			fields = self.central.call(f"{API}.complete_repository_connection", state=self.state)
		except CentralError as error:
			if any(pending in error.message for pending in PENDING_GITHUB):
				return None
			raise
		return DeployApp(self.central, fields)


def get_deploy_request(central: Central, name: str) -> dict:
	"""A deploy request with its tasks and its build and release logs."""
	return central.get(f"{API}.get_deploy_request", name=name)
