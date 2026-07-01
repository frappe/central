export interface ProviderLogin {
  name: string
  label: string
  icon: string
  auth_url: string
}

/** central.api.servers.refresh_assets response (the reconcile result). */
export interface RefreshResponse {
  synced: string[]
  /** Atlas instances that couldn't be reached this pass; their mirror is stale. */
  stale: string[]
}

/** central.api.identity.my_teams item. */
export interface Team {
  name: string
  label: string
  owner: string | null
}

export type MemberStatus = 'Active' | 'Suspended'
export type CapabilityPlane = 'central' | 'atlas' | 'bench'
export type InvitationStatus = 'Pending' | 'Accepted' | 'Expired' | 'Revoked' | 'Declined'

/** central.api.teams.list_team_members item. */
export interface TeamMemberRow {
  user: string
  role: string
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

/** central.api.teams.list_capabilities item — the palette of authorization atoms. */
export interface CapabilityInfo {
  name: string
  plane: CapabilityPlane
  resource: string
  description: string
}

/** central.api.teams.list_team_invitations item (the manager's view). */
export interface InvitationRow {
  name: string
  email: string
  role: string
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
  invited_by: string | null
  expires_on: string | null
  creation: string
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
  team: string
  cluster: string | null
  currency: string
  tier: string | null
  max_spend: number
  current_spend: number
  /** Remaining headroom in the team's currency: a plan is offered only if it fits. */
  available: number
  plans: Record<string, Plan[]>
}
