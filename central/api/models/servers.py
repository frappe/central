from typing import Literal, NotRequired, TypedDict


class RegistryServer(TypedDict):
	name: str
	resource_id: str
	atlas_vm_id: str | None
	title: str
	region: str
	status: str
	plan: str | None
	plan_title: str | None
	frappe_version: str | None
	vcpus: float
	memory_megabytes: int
	disk_gigabytes: float
	ipv6_address: str | None
	public_ipv4: str | None
	public_ipv6: str | None
	image_offering: str | None
	image_title: str | None
	image_description: str | None
	gateway_url: str | None
	state_observed_at: str | None
	has_wireguard_access: bool
	pending_action: str | None
	pilot_audience: str | None
	capabilities: list[str]
	is_access_locked: bool
	is_idle_sleep_available: bool
	sleep_state: str | None
	creation: str
	created_by: str | None
	created_by_name: str | None


class RegistrySite(TypedDict):
	name: str
	subdomain: str | None
	server: str
	url: str
	status: str
	region: str
	pending_action: str | None


class Registry(TypedDict):
	"""A team's servers, self-serve sites and unfinished creations."""

	team: str
	servers: list[RegistryServer]
	sites: list[RegistrySite]
	creations: list[dict]


class OperatorLinks(TypedDict):
	"""Desk and Atlas form links, shown to operators only."""

	desk_url: str
	atlas_url: str | None


class RegionDetails(TypedDict):
	display_name: str
	provider: str | None
	country_code: str | None
	has_wireguard_gateway: bool


class ServerDetails(TypedDict):
	"""One server as its page shows it. `operator_links` is set only for staff."""

	resource_id: str
	atlas_vm_id: str | None
	title: str
	region: str
	status: str
	plan: str | None
	plan_title: str | None
	plan_rate: float | None
	plan_currency: str | None
	plan_billing_cycle: str | None
	frappe_version: str | None
	image_offering: str | None
	application: str | None
	documentation_url: str | None
	vcpus: float
	memory_megabytes: int
	disk_gigabytes: float
	ipv6_address: str | None
	public_ipv4: str | None
	public_ipv6: str | None
	has_public_ipv6: bool
	is_firewall_enabled: bool
	firewall_rulesets: list[str]
	firewall_rules: dict
	is_termination_protected: bool
	has_ipv4_internet: bool
	has_wireguard_access: bool
	ssh_command: str | None
	ssh_keys: list[dict]
	gateway_url: str | None
	creation: str
	created_by: str | None
	created_by_name: str | None
	team_name: str
	operator_links: OperatorLinks | None
	region_details: RegionDetails


class ServerOverview(TypedDict):
	server: ServerDetails


class ServerMetrics(TypedDict):
	"""Usage samples. `points` and `sample_interval_seconds` are present only when `available`."""

	available: bool
	points: NotRequired[list[dict]]
	sample_interval_seconds: NotRequired[int]


class Hostname(TypedDict):
	hostname: str
	kind: Literal["Site", "Custom domain"]


class Region(TypedDict):
	region: str
	status: str
	reachable: bool
	display_name: str
	provider: str
	country_code: str
	latitude: float
	longitude: float


class RefreshServersResponse(TypedDict):
	synced: list[str]
	stale: list[str]
	queued: int


class OpenConsoleResponse(TypedDict):
	url: str


class ResizeServerResponse(TypedDict):
	"""`queued` is false when nothing had to change. The action fields come with a queued resize."""

	queued: bool
	resized: bool
	subscription: NotRequired[str | None]
	action: NotRequired[str]
	status: NotRequired[str]
	resource_id: NotRequired[str | None]
	title: NotRequired[str]
	error: NotRequired[dict | None]


class RenameServerResponse(TypedDict):
	title: str


class PublicIpv4Price(TypedDict):
	rate: float | None
	currency: str


class SetServerPublicIpResponse(TypedDict):
	is_pending: bool


class KeepTrialSiteResponse(TypedDict):
	site: str


class RescueState(TypedDict):
	is_rescue_mode_enabled: bool | None
	is_in_rescue_mode: bool | None


class IdleSleep(TypedDict):
	sleep_after_idle_seconds: int


class ImageOffering(TypedDict):
	name: str
	title: str
	logo: str | None
	description: str | None
	available_in: str


class ImagePage(TypedDict):
	"""One page of a region's images. Ask again with `next_offset` while it is set."""

	items: list[dict]
	next_offset: int | None


class ReadyApp(TypedDict):
	"""A ready-to-run application the region's Cargo has built an image of."""

	application: str
	title: str
	os_version: str | None
	information: str | None
	logo: str | None
	documentation: str | None
	snapshot_id: str


class PlanCatalog(TypedDict):
	"""The plans a new server can take, grouped by plan family, with the image they apply to."""

	currency: str
	plans: dict[str, list[dict]]
	rate_card: dict
	profiles: list[dict]
	image_id: str


class Snapshot(TypedDict):
	name: str
	title: str | None
	server: str
	server_title: str
	region: str
	snapshot_type: str
	status: str
	size_mib: int | None
	size_gib: int
	creation: str
	expires_at: str | None
	is_free: bool
	is_billed: bool
	is_restorable: bool
	monthly_cost: float | None
	image_offering: str | None
	atlas_image_id: str | None
	error_detail: str | None
	capabilities: list[str]


class AutomaticSnapshots(TypedDict):
	resource_id: str
	automatic: bool
	region_automatic: bool


class SnapshotList(TypedDict):
	"""`server` is set when the list is for one server."""

	snapshots: list[Snapshot]
	currency: str
	rates: dict[str, float | None]
	free_per_server: int
	daily_retention_hours: int
	server: NotRequired[AutomaticSnapshots]


class SnapshotPricing(TypedDict):
	rate_per_gib: float | None
	currency: str
	free_per_server: int
	daily_retention_hours: int


class SnapshotName(TypedDict):
	name: str


class DeleteSnapshotsResponse(TypedDict):
	"""`failed` maps each snapshot that was not deleted to the reason."""

	deleted: list[str]
	failed: dict[str, str]


class FirewallRulesetSummary(TypedDict):
	name: str
	title: str
	rules: dict
	last_sync_error: str | None
	server_count: int


class TeamSshKey(TypedDict):
	name: str
	title: str
	public_key: str
	fingerprint: str
	server_count: int
	last_sync_error: NotRequired[str | None]


class RotateTeamSshKeyResponse(TypedDict):
	name: str
	fingerprint: str


class WireGuardDevice(TypedDict):
	"""`added_by_name` and `can_delete` come with the device list."""

	name: str
	title: str
	region: str
	status: str
	added_by: str
	public_key: str
	address: str
	allowed_ips: str
	endpoint: str
	gateway_public_key: str
	creation: str
	added_by_name: NotRequired[str | None]
	can_delete: NotRequired[bool]


class WireGuardRegion(TypedDict):
	name: str
	display_name: str


class WireGuardServer(TypedDict):
	resource_id: str
	title: str
	region: str
	ipv6_address: str | None
	has_wireguard_access: bool
	is_blocked_by_firewall: bool


class WireGuardDevices(TypedDict):
	devices: list[WireGuardDevice]
	regions: list[WireGuardRegion]
	servers: list[WireGuardServer]


class DeleteWireguardDeviceResponse(TypedDict):
	is_removed: bool
