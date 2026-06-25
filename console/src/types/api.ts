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
