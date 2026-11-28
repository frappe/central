from typing import Literal, NotRequired, TypedDict


class SiteDomain(TypedDict):
	domain: str


class OpenTrial(TypedDict):
	"""The owner's open trial. The site fields are left out for a caller who cannot view its team."""

	state: str
	product: str
	product_title: str | None
	product_logo: str | None
	site: NotRequired[str]
	server: NotRequired[str]
	address: NotRequired[str]
	url: NotRequired[str]
	ends_on: NotRequired[str | None]
	deletes_on: NotRequired[str | None]


class InstallTrialAppResponse(TypedDict):
	site: str
	task_id: str | None
	status: str


class AppInstallProgress(TypedDict):
	status: Literal["queued", "running", "success", "failed", "unreachable"]
	queue_position: int | None
	started_at: str | None
	error: str | None


class SubdomainAvailability(TypedDict):
	subdomain: str
	available: bool
	reason: str | None


class CreateTrialTeamResponse(TypedDict):
	team: str


class SiteState(TypedDict):
	name: str
	status: str
	url: str
	ready: bool
	login_url: str | None
	login_pending: bool
	claimed: bool


class JourneyRegion(TypedDict):
	title: str
	country_code: str | None
	latitude: float | None
	longitude: float | None


class SetupJourney(TypedDict):
	phase: str
	subdomain: str | None
	domain: str | None
	region: JourneyRegion
	started_at: str
	eta_seconds: int | None
	reference: str


class OnboardingStatus(TypedDict):
	"""`site` once the site exists, `creation` while it is being made or after it failed."""

	site: SiteState | None
	creation: dict | None
	journey: SetupJourney | None
	is_free_trial: bool
