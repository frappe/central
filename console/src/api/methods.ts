// Whitelisted method paths in one place. `method(path)` builds the v2 method URL
// the data-fetching composables call. These are the live, capability-gated,
// team-scoped endpoints under central/api/.

export function method(path: string): string {
  return `/api/v2/method/${path}`
}

export const API = {
  // ── Identity / capability IAM (central.api.identity) ──
  myTeams: 'central.api.identity.my_teams',
  myCapabilities: 'central.api.identity.my_capabilities',

  // ── Servers (central.api.servers) ──
  registry: 'central.api.servers.registry',
  listInstances: 'central.api.servers.list_instances',
  refreshAssets: 'central.api.servers.refresh_assets',
  createServer: 'central.api.servers.create_server',
  startServer: 'central.api.servers.start_server',
  stopServer: 'central.api.servers.stop_server',
  terminateServer: 'central.api.servers.terminate_server',

  // ── Auth / SMB signup (central.api.auth) ──
  signUp: 'central.api.auth.sign_up',
  verifySignup: 'central.api.auth.verify_signup',
  resendSignupCode: 'central.api.auth.resend_signup_code',

  // ── Self-serve sites (central.api.sites) ──
  checkSubdomain: 'central.api.sites.check_subdomain',
  siteDomain: 'central.api.sites.site_domain',
  createSite: 'central.api.sites.create_site',
  getSite: 'central.api.sites.get_site',

  // ── SSO open-in-bench (central.api.sso) ──
  getBenchLink: 'central.api.sso.get_bench_link',

  // ── Billing catalog (central.billing.api.dashboard.catalog) ──
  eligiblePlans: 'central.billing.api.dashboard.catalog.get_eligible_plans',
} as const
