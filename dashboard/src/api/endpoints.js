// Whitelisted method paths, one place. `m(path)` builds the v2 method URL.
//
// ✅ billing.* — existing, grounded endpoints (central.billing.api.dashboard.*).
// ✅ central.* — team/identity (central.iam / central.api).
// 🟡 atlas.*   — PROPOSED endpoints; no DocType/API specced yet. The Atlas screens
//    fall back to dummy data (src/pages/atlas/mock.js) until these land.

export function m(method) {
  return `/api/v2/method/${method}`
}

const D = 'central.billing.api.dashboard'

export const API = {
  // ── Capability IAM / team scope (central-owned) ──
  myCapabilities: `central.iam.my_capabilities`,
  whoami: `${D}.whoami`,
  myTeams: `central.iam.my_teams`,
  searchTeams: `central.iam.search_teams`,

  // ── Billing: reads ──
  teamOverview: `${D}.get_team_overview`,
  forecast: `${D}.get_forecast`,
  trustTier: `${D}.get_trust_tier`,
  creditBalance: `${D}.get_credit_balance`,
  creditLedger: `${D}.credit_ledger`,
  invoices: `${D}.list_invoices`,
  invoice: `${D}.get_invoice`,
  paymentAttempts: `${D}.list_payment_attempts`,
  paymentMethods: `${D}.list_payment_methods`,
  paymentMethodOptions: `${D}.get_payment_method_options`,
  subscriptions: `${D}.list_subscriptions`,
  billingProfile: `${D}.get_billing_profile`,
  billingGeo: `${D}.get_billing_geo`,
  billingSettings: `${D}.get_billing_settings`,
  collectionStatus: `${D}.get_collection_status`,
  notifications: `${D}.list_notifications`,
  notificationPreferences: `${D}.get_notification_preferences`,

  // ── Billing: mutations (billing:manage) ──
  payInvoice: `${D}.pay_invoice`,
  payInvoiceCheckout: `${D}.pay_invoice_checkout`,
  confirmInvoiceCheckout: `${D}.confirm_invoice_checkout`,
  createTopupOrder: `${D}.create_topup_order`,
  confirmTopup: `${D}.confirm_topup`,
  initiateCardSetup: `${D}.initiate_card_setup`,
  confirmCard: `${D}.confirm_card`,
  setupPaymentMethodOrder: `${D}.setup_payment_method_order`,
  confirmPaymentMethodOrder: `${D}.confirm_payment_method_order`,
  setDefaultPaymentMethod: `${D}.set_default_payment_method`,
  reorderPaymentMethods: `${D}.reorder_payment_methods`,
  removePaymentMethod: `${D}.remove_payment_method`,
  saveBillingProfile: `${D}.save_billing_profile`,
  saveBillingSettings: `${D}.save_billing_settings`,
  setCollectionMode: `${D}.set_collection_mode`,
  saveNotificationPreferences: `${D}.save_notification_preferences`,

  // ── Team & identity (central.iam) ──
  listTeamMembers: `central.iam.list_team_members`,
  listRoles: `central.iam.list_team_roles`,
  listCapabilities: `central.iam.list_capabilities`,
  inviteMember: `central.iam.invite_team_member`,
  setMemberRole: `central.iam.set_team_member_role`,
  setMemberStatus: `central.iam.set_team_member_status`,
  removeMember: `central.iam.remove_team_member`,
  createCustomRole: `central.iam.create_custom_role`,

  // ── Atlas registry (✅ live: list + refresh + SSO open-in-bench) ──
  atlasRegistry: `central.atlas.registry`,
  refreshAssets: `central.atlas.refresh_assets`,
  getBenchLink: `central.sso.get_bench_link`,
  // ── Atlas (🟡 proposed; still mocked) ──
  atlasVms: `central.atlas.list_vms`,
  atlasRegion: `central.atlas.current_region`,
  atlasAccessRequests: `central.atlas.list_access_requests`,
}
