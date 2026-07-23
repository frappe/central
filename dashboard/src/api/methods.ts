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
	createComposedServer: 'central.api.servers.create_composed_server',
	frappeVersions: 'central.api.servers.frappe_versions',
	startServer: 'central.api.servers.start_server',
	stopServer: 'central.api.servers.stop_server',
	terminateServer: 'central.api.servers.terminate_server',
	listResources: 'central.api.resources.list_resources',

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

	// ── Auth / SMB signup (central.api.auth) ──
	signUp: 'central.api.auth.sign_up',
	verifySignup: 'central.api.auth.verify_signup',
	resendSignupCode: 'central.api.auth.resend_signup_code',

	// ── Self-serve sites (central.api.sites) ──
	checkSubdomain: 'central.api.sites.check_subdomain',
	siteDomain: 'central.api.sites.site_domain',
	createSite: 'central.api.sites.create_site',
	getSite: 'central.api.sites.get_site',
	terminateSite: 'central.api.sites.terminate_site',

	// ── SSO open-in-bench (central.api.sso) ──
	getBenchLink: 'central.api.sso.get_bench_link',

	// ── Billing catalog (central.billing.api.dashboard.catalog) ──
	eligiblePlans: 'central.billing.api.dashboard.catalog.get_eligible_plans',
	composedConfig: 'central.billing.api.dashboard.catalog.get_composed_config',
	resizeComposedConfig:
		'central.billing.api.dashboard.catalog.resize_composed_config',
	resizeServer: 'central.billing.api.dashboard.catalog.resize_server',

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
	meteredServices: 'central.billing.api.dashboard.get_metered_services',
	billingProfile: 'central.billing.api.dashboard.get_billing_profile',
	billingGeo: 'central.billing.api.dashboard.get_billing_geo',
	billingSettings: 'central.billing.api.dashboard.get_billing_settings',
	collectionStatus: 'central.billing.api.dashboard.get_collection_status',
	notifications: 'central.billing.api.dashboard.list_notifications',
	notificationBadge: 'central.billing.api.dashboard.notification_badge',
	notificationPreferences:
		'central.billing.api.dashboard.get_notification_preferences',

	// ── Billing: mutations (POST, billing:manage) ──
	payInvoice: 'central.billing.api.dashboard.pay_invoice',
	payInvoiceCheckout: 'central.billing.api.dashboard.pay_invoice_checkout',
	confirmInvoiceCheckout:
		'central.billing.api.dashboard.confirm_invoice_checkout',
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
	saveNotificationPreferences:
		'central.billing.api.dashboard.save_notification_preferences',
	markNotificationRead: 'central.billing.api.dashboard.mark_notification_read',
	markAllNotificationsRead:
		'central.billing.api.dashboard.mark_all_notifications_read',
	pauseSubscription: 'central.billing.api.dashboard.pause_subscription',
	resumeSubscription: 'central.billing.api.dashboard.resume_subscription',
	subscribeMeteredService:
		'central.billing.api.dashboard.subscribe_metered_service',
} as const
