/** central.api.servers.refresh_servers response (the reconcile result). */
export interface RefreshResponse {
	synced: string[]
	/** Atlas instances that couldn't be reached this pass; their mirror is stale. */
	stale: string[]
}

/** central.api.identity.my_teams item. */
/** A console onboarding step that a team stores. Mirrors Team Onboarding Step.step. */
export type OnboardingStepKey = 'invite' | 'billing' | 'start'

export interface Team {
	name: string
	label: string
	/** Public file URL of the team's logo, or null for the initial-letter tint. */
	logo: string | null
	owner: string | null
	role: string | null
	members: number
	created: string | null
	/** The steps the caller still has to answer as owner. Empty for a team they do not own. */
	onboarding: OnboardingStepKey[]
	/** A suspended team is listed so the console can say why it cannot open it. */
	status: 'Active' | 'Suspended'
	/** Set when a System Manager opened the console as this team's owner. */
	is_impersonated?: boolean
}

export type MemberStatus = 'Active' | 'Suspended'
export type CapabilityPlane = 'central' | 'atlas' | 'bench'
export type InvitationStatus =
	| 'Pending'
	| 'Accepted'
	| 'Expired'
	| 'Revoked'
	| 'Declined'

export type ResourceType = '*' | 'Server' | 'Site'

export interface TeamMemberRoleAssignment {
	role: string
	resource_type: ResourceType
	resource_name: string | null
}

/** central.api.teams.list_team_members item. */
export interface TeamMemberRow {
	user: string
	full_name: string
	/** The frappe User's profile photo URL, when they've set one. */
	user_image: string | null
	roles: TeamMemberRoleAssignment[]
	status: MemberStatus
	is_owner: boolean
}

/** central.api.teams.list_team_roles item — a role plus the capabilities it grants. */
export interface TeamRoleRow {
	name: string
	role_name: string
	is_system: 0 | 1
	team: string | null
	capabilities: string[]
}

/** Capability document used by the role builder. */
export interface CapabilityInfo {
	name: string
	plane: CapabilityPlane
	resource: string
	description: string
}

/** central.api.servers.registry response. */
export interface TeamRegistry {
	team: string
	servers: {
		name: string
		resource_id: string
		title: string
		region: string
	}[]
	sites: { name: string; subdomain: string; region: string }[]
}

/** Team Invitation document shown in the manager view. */
export interface InvitationRow {
	name: string
	email: string
	role: string
	resource_type: ResourceType
	resource_name: string | null
	status: InvitationStatus
	invited_by: string | null
	expires_on: string | null
	accepted_by: string | null
	accepted_at: string | null
	creation: string
}

/** central.api.identity.my_invitations item (the invitee's inbox). */
export interface MyInvitation {
	name: string
	team: string
	team_name: string
	role: string
	/** The role's display name; a custom role's `role` is an opaque record name. */
	role_name: string
	invited_by: string | null
	expires_on: string | null
	creation: string
}

/** An invitation as the join page reads it by its emailed token. */
export interface InvitationSummary {
	name: string
	email: string
	status: 'Pending' | 'Accepted' | 'Expired' | 'Revoked' | 'Declined'
	team_name: string
	invited_by: string
	role: string
	expires_on: string
	has_account: boolean
}

/** One bundled resource in a plan (central Plan Includes). */
export interface PlanInclude {
	resource_type: 'Compute' | 'Memory' | 'Disk' | 'Transfer' | 'IP' | 'Snapshot'
	quantity: number
	unit: string
}

/** An eligible plan from the billing catalog, priced for the team's currency
 *  on the chosen region.
 *  (central.billing.api.dashboard.catalog.get_eligible_plans) */
export interface Plan {
	plan: string
	title: string
	sub_category: string
	billing_cycle: 'Monthly' | 'Annual'
	currency: string
	cluster: string | null
	rate: number
	includes: PlanInclude[]
}

/** get_eligible_plans response: the offered menu plus the trust-tier headroom
 *  (spend cap minus current run-rate) that shaped it. `plans` is grouped by
 *  sub-category — keys in canonical order, rows cheapest-first, unset sub-category
 *  folded into "General"; a forbidden cluster yields an empty map. */
export interface ProvisionablePlans {
	image_id?: string
	team: string
	cluster: string | null
	currency: string
	tier: string | null
	max_spend: number
	current_spend: number
	/** Remaining headroom in the team's currency: a plan is offered only if it fits. */
	available: number
	spend_limit_enforced: boolean
	/** The monthly transfer every server includes, from Central Settings. */
	included_transfer_gb: number
	plans: Record<string, Plan[]>
	/** Per-resource component rates for "design your own" (#79). Empty when a
	 *  component isn't priced for the team's currency — composed configs not offered. */
	rate_card: RateCard
	/** Optimisation-profile bounds the slider snaps + clamps to (#81). */
	profiles: Profile[]
	/** The region's live provisioning capacity — narrows the menu and caps the slider. */
	capacity: Capacity
}

/** The largest single VM a region can seat right now (Atlas capacity API). */
export interface LargestVm {
	vcpus: number
	memory_megabytes: number
	disk_gigabytes: number
}

/** Live-capacity summary for the create-server menu (get_eligible_plans). */
export interface Capacity {
	/** Whether live capacity narrowed this menu. Capacity is never gated today. */
	gated: boolean
	/** Whether the region can seat any new VM right now — False → show "region is full". */
	available: boolean
	/** The winning host has an unreported axis → `largest_vm` is sentinel, size unknown. */
	unmeasured: boolean
	/** The biggest placeable shape — the composed slider's hard ceiling. Null when ungated
	 *  or when the region has no room at all. */
	largest_vm: LargestVm | null
}

/** The per-resource rate card: `{ Compute: { rate, unit }, … }`. */
export type RateCard = Partial<
	Record<'Compute' | 'Memory' | 'Disk', { rate: number; unit: string }>
>

/** A compute optimisation profile's runtime bounds (Plan Sub-Category, #81). */
export interface Profile {
	sub_category: string
	/** GB RAM per vCPU: RAM = vCPU × ram_ratio. */
	ram_ratio: number
	/** Allowed vCPU values the slider snaps to. */
	vcpu_steps: number[]
	/** Allowed storage values (GB) the slider snaps to, within [disk_min, disk_max]. */
	disk_steps: number[]
	disk_min: number
	disk_max: number
}

/** A design-your-own composition: quantity per compute primitive. */
export interface ComposedConfig {
	sub_category: string
	vcpus: number
	memory_gb: number
	disk_gb: number
}

export interface TrialSiteState {
	name: string
	status: string
	url: string | null
	ready: boolean
	claimed: boolean
	login_url: string | null
	login_pending: boolean
}

/** The owner's open free trial, which a new signup offers before it asks for another site. */
export interface OpenTrial {
	state: 'Active' | 'Ended' | 'Setting up'
	product: string | null
	product_title: string
	/** The Product's logo, or null for a plain Frappe Cloud trial. */
	product_logo?: string | null
	/** Absent while the site is still being set up. */
	site?: string
	server?: string
	address?: string
	url?: string
	ends_on?: string | null
	deletes_on?: string | null
}

/** A Pilot task's state while it installs an app on a trial site. */
export type AppInstallStatus =
	| 'queued'
	| 'running'
	| 'success'
	| 'failed'
	| 'killed'

/** The install that `install_trial_app` started: the bench's name for the site and its task. */
export interface TrialAppInstall {
	site: string
	task_id: string | null
	status: AppInstallStatus
}

export interface TrialAppInstallProgress {
	/** `unreachable`: the site did not answer this poll, so the page asks again. */
	status: AppInstallStatus | 'unreachable'
	/** Tasks ahead of this one on the server while it is queued. */
	queue_position: number | null
	started_at: string | null
	/** Customer copy for a failed install. The reason is on the Site for operators. */
	error: string | null
}

/** The milestone a new site is working towards, as Central reads it. */
export type SetupPhase = 'booking' | 'server' | 'app' | 'signing' | 'failed'

export interface SetupJourney {
	phase: SetupPhase
	subdomain: string | null
	domain: string | null
	region: {
		title: string | null
		country_code: string | null
		/** Read with `hasMapCoords`: a region without coordinates reports 0/0. */
		latitude?: number
		longitude?: number
	}
	started_at: string | null
	/** The median wait of recent trials in the region, or null with too few of them. */
	eta_seconds: number | null
	/** The creation request's name, which support can look up. */
	reference: string | null
}

export interface TrialOnboardingStatus {
	site: TrialSiteState | null
	creation: {
		action: string
		status: string
		title: string
		error: { message: string } | null
	} | null
	journey: SetupJourney | null
}
