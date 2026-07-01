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
  myInvitations: 'central.api.identity.my_invitations',

  // ── Team roster, roles & invitations (central.api.teams) ──
  listTeamMembers: 'central.api.teams.list_team_members',
  listTeamRoles: 'central.api.teams.list_team_roles',
  listCapabilities: 'central.api.teams.list_capabilities',
  listTeamInvitations: 'central.api.teams.list_team_invitations',
  createTeam: 'central.api.teams.create_team',
  renameTeam: 'central.api.teams.rename_team',
  transferOwnership: 'central.api.teams.transfer_team_ownership',
  deleteTeam: 'central.api.teams.delete_team',
  inviteTeamMember: 'central.api.teams.invite_team_member',
  setTeamMemberRole: 'central.api.teams.set_team_member_role',
  setTeamMemberStatus: 'central.api.teams.set_team_member_status',
  removeTeamMember: 'central.api.teams.remove_team_member',
  createCustomRole: 'central.api.teams.create_custom_role',
  deleteCustomRole: 'central.api.teams.delete_custom_role',
  resendInvitation: 'central.api.teams.resend_invitation',
  revokeInvitation: 'central.api.teams.revoke_invitation',
  acceptInvitation: 'central.api.teams.accept_invitation',
  declineInvitation: 'central.api.teams.decline_invitation',

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
