// Domain types for the Central Console. These mirror the server-side shapes of
// the Asset / Atlas Instance doctypes and the capability IAM (central/api/servers.py,
// central/iam.py). Kept in one place so screens and composables share them.

/** A team's VM, mirrored from Atlas into the Asset doctype. The console only
 *  ever reads this (the mirror is written by the Atlas event push / reconcile). */
export interface Server {
  /** Asset.resource_id — the Atlas VM id (source of truth, a UUID). */
  resource_id: string
  /** Human label mirrored from the Atlas VM. */
  title: string | null
  /** Atlas Instance (region / cluster) this VM lives in. */
  cluster: string
  status: ServerStatus
  vcpus: number | null
  memory_megabytes: number | null
  disk_gigabytes: number | null
  ipv6_address: string | null
  public_ipv4: string | null
  /** Bench gateway Central deep-links into; empty until reported. */
  gateway_url: string | null
  last_synced_at: string | null
}

/** Mirrors the Atlas VM status verbatim. Atlas is the source of truth and can
 *  report values beyond the Asset doctype's declared options (e.g. Provisioning),
 *  so we keep the known states for autocomplete but accept any string. */
export type ServerStatus =
  | 'Pending'
  | 'Provisioning'
  | 'Running'
  | 'Paused'
  | 'Stopped'
  | 'Failed'
  | 'Terminated'
  | (string & {})

/** central.api.servers.registry response. */
export interface RegistryResponse {
  team: string
  assets: Server[]
}

/** central.api.servers.refresh_assets response (the reconcile result). */
export interface RefreshResponse {
  synced: string[]
  /** Atlas instances that couldn't be reached this pass; their mirror is stale. */
  stale: string[]
}

/** A region the team can place servers in — an Atlas Instance row.
 *  (central.api.servers.list_instances) */
export interface Region {
  region: string
  status: 'Active' | 'Draining' | 'Disabled'
  reachable: boolean
}

/** central.api.identity.my_teams item. */
export interface Team {
  name: string
  label: string
  owner: string | null
}

/** central.api.sso.get_bench_link response. */
export interface BenchLinkResponse {
  url: string
}
