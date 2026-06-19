// Whitelisted method paths in one place. `method(path)` builds the v2 method URL
// the data-fetching composables call. These are the live, capability-gated,
// team-scoped endpoints in central/atlas.py, central/iam.py and central/sso.py —
// the same contract the legacy dashboard uses.

export function method(path: string): string {
  return `/api/v2/method/${path}`
}

export const API = {
  // ── Identity / capability IAM (central.iam) ──
  myTeams: 'central.iam.my_teams',
  myCapabilities: 'central.iam.my_capabilities',

  // ── Servers (central.atlas) ──
  registry: 'central.atlas.registry',
  listInstances: 'central.atlas.list_instances',
  refreshAssets: 'central.atlas.refresh_assets',
  createServer: 'central.atlas.create_server',
  startServer: 'central.atlas.start_server',
  stopServer: 'central.atlas.stop_server',
  terminateServer: 'central.atlas.terminate_server',

  // ── SSO open-in-bench (central.sso) ──
  getBenchLink: 'central.sso.get_bench_link',
} as const
