// Whitelisted method paths in one place. `method(path)` builds the v2 method URL
// the data-fetching composables call. These are the live, capability-gated,
// team-scoped endpoints under central/api/.

export function method(path: string): string {
	return `/api/v2/method/${path}`
}

/** The v1 method URL, for a raw `frappeRequest`.
 *
 *  `frappeRequest` returns `data.message`, which only a v1 response carries: v2 answers
 *  `{data: ...}` and the call silently resolves to undefined. Use `method()` for the
 *  data-fetching composables, and this for anything that calls `frappeRequest` itself. */
export function methodV1(path: string): string {
	return `/api/method/${path}`
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
	myProfile: 'central.api.identity.my_profile',
	updateProfile: 'central.api.identity.update_profile',
	changePassword: 'central.api.auth.change_password',
	transferOwnership: 'central.api.teams.transfer_team_ownership',
	deleteTeam: 'central.api.teams.delete_team',
	inviteTeamMember: 'central.api.teams.invite_team_member',
	setTeamMemberRoles: 'central.api.teams.set_team_member_roles',
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
	refreshServers: 'central.api.servers.refresh_servers',
	actionStatus: 'central.api.servers.action_status',
	retryAction: 'central.api.servers.retry_action',
	createServer: 'central.api.servers.create_server',
	createComposedServer: 'central.api.servers.create_composed_server',
	startServer: 'central.api.servers.start_server',
	stopServer: 'central.api.servers.stop_server',
	restartServer: 'central.api.servers.restart_server',
	resizeServer: 'central.api.servers.resize_server',
	terminateServer: 'central.api.servers.terminate_server',
	serverOverview: 'central.api.servers.server_overview',
	serverHostnames: 'central.api.servers.server_hostnames',

	// ── Snapshots (central.api.snapshots) ──
	// server:view reads them and their price; server:snapshot takes, keeps and deletes.
	listSnapshots: 'central.api.snapshots.list_snapshots',
	snapshotPricing: 'central.api.snapshots.snapshot_pricing',
	takeSnapshot: 'central.api.snapshots.take_snapshot',
	keepSnapshot: 'central.api.snapshots.keep_snapshot',
	deleteSnapshots: 'central.api.snapshots.delete_snapshots',
	setAutomaticSnapshots: 'central.api.snapshots.set_automatic_snapshots',

	// ── Managed add-on services (central.services.api.dashboard) ──
	// service:view for the reads, service:manage for the mutations + key reveal.
	// Per-site enable/disable is a bench (Pilot) surface, not a console method.
	listOffers: 'central.services.api.dashboard.list_offers',
	serviceInstance: 'central.services.api.dashboard.get_instance',
	activateService: 'central.services.api.dashboard.activate_service',
	generateApiKey: 'central.services.api.dashboard.generate_api_key',
	listApiKeys: 'central.services.api.dashboard.list_api_keys',
	revealApiKey: 'central.services.api.dashboard.reveal_api_key',
	revokeApiKey: 'central.services.api.dashboard.revoke_api_key',
	listBuckets: 'central.services.api.dashboard.list_buckets',
	createBucket: 'central.services.api.dashboard.create_bucket',
	revealBucketKey: 'central.services.api.dashboard.reveal_bucket_key',
	revokeBucketKey: 'central.services.api.dashboard.revoke_bucket_key',

	// ── Auth / SMB signup (central.api.auth) ──
	signUp: 'central.api.auth.sign_up',
	verifySignup: 'central.api.auth.verify_signup',
	resendSignupCode: 'central.api.auth.resend_signup_code',

	// ── Self-serve sites (central.api.sites) ──
	// A site is the machine its Pilot image was baked on, and has no lifecycle of its
	// own. The customer names it; the address the region derives stays ours.
	siteDomain: 'central.api.sites.site_domain',
	checkSubdomain: 'central.api.sites.check_subdomain',
	createTrialSite: 'central.api.sites.create_trial_site',
	onboardingStatus: 'central.api.sites.onboarding_status',
	claimSite: 'central.api.sites.claim_site',
	getSite: 'central.api.sites.get_site',
	loginSite: 'central.api.sites.login_site',
	terminateSite: 'central.api.sites.terminate_site',

	// ── SSO open-in-bench (central.api.sso) ──
	getBenchLink: 'central.api.sso.get_bench_link',

	// ── Billing catalog (central.billing.api.dashboard.catalog) ──
	eligiblePlans: 'central.billing.api.dashboard.catalog.get_eligible_plans',
	composedConfig: 'central.billing.api.dashboard.catalog.get_composed_config',

	// ── Billing: reads (central.billing.api.dashboard.*, billing:view) ──
	// The dashboard package re-exports every submodule fn, so these flat paths are
	// stable regardless of which module (account/invoices/methods) owns them.
	teamOverview: 'central.billing.api.dashboard.get_team_overview',
	forecast: 'central.billing.api.dashboard.get_forecast',
	trustTier: 'central.billing.api.dashboard.get_trust_tier',
	creditBalance: 'central.billing.api.dashboard.get_credit_balance',
	creditLedger: 'central.billing.api.dashboard.credit_ledger',
	invoices: 'central.billing.api.dashboard.list_invoices',
	invoice: 'central.billing.api.dashboard.get_invoice',
	paymentAttempts: 'central.billing.api.dashboard.list_payment_attempts',
	paymentMethods: 'central.billing.api.dashboard.list_payment_methods',
	paymentMethodOptions:
		'central.billing.api.dashboard.get_payment_method_options',
	subscriptions: 'central.billing.api.dashboard.list_subscriptions',
	projects: 'central.billing.api.dashboard.list_projects',
	nextPayment: 'central.billing.api.dashboard.get_next_payment',
	paymentSchedule: 'central.billing.api.dashboard.get_payment_schedule',
	cycleCosts: 'central.billing.api.dashboard.get_cycle_costs',
	spendHistory: 'central.billing.api.dashboard.get_spend_history',
	statement: 'central.billing.api.dashboard.get_statement',
	taxSummary: 'central.billing.api.dashboard.get_tax_summary',
	refunds: 'central.billing.api.dashboard.list_refunds',
	exportCsv: 'central.billing.api.dashboard.export_csv',
	meteredServices: 'central.billing.api.dashboard.get_metered_services',
	billingProfile: 'central.billing.api.dashboard.get_billing_profile',
	billingGeo: 'central.billing.api.dashboard.get_billing_geo',
	billingSettings: 'central.billing.api.dashboard.get_billing_settings',
	collectionStatus: 'central.billing.api.dashboard.get_collection_status',
	notifications: 'central.notification.api.list_notifications',
	notificationBadge: 'central.notification.api.notification_badge',
	notificationPreferences: 'central.notification.api.get_user_preferences',

	// ── Billing: mutations (POST, billing:manage) ──
	payInvoice: 'central.billing.api.dashboard.pay_invoice',
	payInvoiceCheckout: 'central.billing.api.dashboard.pay_invoice_checkout',
	confirmInvoiceCheckout:
		'central.billing.api.dashboard.confirm_invoice_checkout',
	topupOptions: 'central.billing.api.dashboard.get_topup_options',
	createTopupOrder: 'central.billing.api.dashboard.create_topup_order',
	confirmTopup: 'central.billing.api.dashboard.confirm_topup',
	initiateCardSetup: 'central.billing.api.dashboard.initiate_card_setup',
	confirmCard: 'central.billing.api.dashboard.confirm_card',
	setupPaymentMethodOrder:
		'central.billing.api.dashboard.setup_payment_method_order',
	confirmPaymentMethodOrder:
		'central.billing.api.dashboard.confirm_payment_method_order',
	setDefaultPaymentMethod:
		'central.billing.api.dashboard.set_default_payment_method',
	reorderPaymentMethods:
		'central.billing.api.dashboard.reorder_payment_methods',
	removePaymentMethod: 'central.billing.api.dashboard.remove_payment_method',
	saveBillingProfile: 'central.billing.api.dashboard.save_billing_profile',
	saveBillingSettings: 'central.billing.api.dashboard.save_billing_settings',
	setCollectionMode: 'central.billing.api.dashboard.set_collection_mode',
	saveNotificationPreferences: 'central.notification.api.save_user_preferences',
	markNotificationRead: 'central.notification.api.mark_notification_read',
	markAllNotificationsRead:
		'central.notification.api.mark_all_notifications_read',
	pauseSubscription: 'central.billing.api.dashboard.pause_subscription',
	resumeSubscription: 'central.billing.api.dashboard.resume_subscription',
	setSubscriptionProject:
		'central.billing.api.dashboard.set_subscription_project',
	createProject: 'central.billing.api.dashboard.create_project',
	renameProject: 'central.billing.api.dashboard.rename_project',
	setProjectEnabled: 'central.billing.api.dashboard.set_project_enabled',
	setProjectSpendingLimit:
		'central.billing.api.dashboard.set_project_spending_limit',
	subscribeMeteredService:
		'central.billing.api.dashboard.subscribe_metered_service',
} as const
