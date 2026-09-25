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
	myTeams: 'central.api.identity.my_teams',
	myCapabilities: 'central.api.identity.my_capabilities',
	myInvitations: 'central.api.identity.my_invitations',

	listTeamMembers: 'central.api.teams.list_team_members',
	listTeamRoles: 'central.api.teams.list_team_roles',
	createTeam: 'central.api.teams.create_team',
	setOnboardingStep: 'central.api.teams.set_onboarding_step',
	skipOnboarding: 'central.api.teams.skip_onboarding',
	renameTeam: 'central.api.teams.rename_team',
	setTeamLogo: 'central.api.teams.set_team_logo',
	myProfile: 'central.api.identity.my_profile',
	updateProfile: 'central.api.identity.update_profile',
	setProfilePhoto: 'central.api.identity.set_profile_photo',
	transferOwnership: 'central.api.teams.transfer_team_ownership',
	deleteTeam: 'central.api.teams.delete_team',
	leaveTeam: 'central.api.teams.leave_team',
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
	getInvitation: 'central.api.teams.get_invitation',
	signUpWithInvitation: 'central.api.auth.sign_up_with_invitation',

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
	openConsole: 'central.api.servers.open_console',
	resizeServer: 'central.api.servers.resize_server',
	terminateServer: 'central.api.servers.terminate_server',
	serverOverview: 'central.api.servers.server_overview',
	serverMetrics: 'central.api.servers.server_metrics',
	serverHostnames: 'central.api.servers.server_hostnames',
	listImageOfferings: 'central.api.images.list_offerings',
	listRegionalImages: 'central.api.images.list_images',
	listTeamSSHKeys: 'central.api.ssh_keys.list_team_ssh_keys',
	createTeamSSHKey: 'central.api.ssh_keys.create_team_ssh_key',
	rotateTeamSSHKey: 'central.api.ssh_keys.rotate_team_ssh_key',
	retryTeamSSHKeySync: 'central.api.ssh_keys.retry_team_ssh_key_sync',
	deleteTeamSSHKey: 'central.api.ssh_keys.delete_team_ssh_key',

	// ── Snapshots (central.api.snapshots) ──
	// server:view reads them and their price; server:snapshot takes, keeps and deletes.
	listSnapshots: 'central.api.snapshots.list_snapshots',
	snapshotPricing: 'central.api.snapshots.snapshot_pricing',
	takeSnapshot: 'central.api.snapshots.take_snapshot',
	keepSnapshot: 'central.api.snapshots.keep_snapshot',
	deleteSnapshots: 'central.api.snapshots.delete_snapshots',
	setAutomaticSnapshots: 'central.api.snapshots.set_automatic_snapshots',

	ai: 'central.services.api.ai.get_ai',
	enableAI: 'central.services.api.ai.enable_ai',
	aiUsage: 'central.services.api.ai.get_usage',
	aiApiKeys: 'central.services.api.ai.list_api_keys',
	createAIApiKey: 'central.services.api.ai.create_api_key',
	revokeAIApiKey: 'central.services.api.ai.revoke_api_key',
	setAIApiKeyBalanceAccess:
		'central.services.api.ai.set_api_key_balance_access',

	objectStorage: 'central.services.api.storage.get_object_storage',
	bucketUsage: 'central.services.api.storage.get_bucket_usage',
	createBucket: 'central.services.api.storage.create_bucket',
	rotateBucketCredentials: 'central.services.api.storage.rotate_credentials',
	setBucketQuota: 'central.services.api.storage.set_bucket_quota',
	deleteBucket: 'central.services.api.storage.delete_bucket',
	listBucketObjects: 'central.services.api.storage.list_objects',
	bucketObjectUrl: 'central.services.api.storage.get_object_url',

	getProduct: 'central.api.signups.get_product',
	sendCode: 'central.api.auth.send_code',
	verifyCode: 'central.api.auth.verify_code',
	siteDomain: 'central.api.sites.site_domain',
	checkSubdomain: 'central.api.sites.check_subdomain',
	createTrialTeam: 'central.api.sites.create_trial_team',
	createTrialSite: 'central.api.sites.create_trial_site',
	onboardingStatus: 'central.api.sites.onboarding_status',
	claimSite: 'central.api.sites.claim_site',
	getSite: 'central.api.sites.get_site',
	loginSite: 'central.api.sites.login_site',
	terminateSite: 'central.api.sites.terminate_site',

	getBenchLink: 'central.api.sso.get_bench_link',

	eligiblePlans: 'central.billing.api.dashboard.catalog.get_eligible_plans',
	composedConfig: 'central.billing.api.dashboard.catalog.get_composed_config',

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
	recheckGstStatus: 'central.billing.api.dashboard.recheck_gst_status',
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
