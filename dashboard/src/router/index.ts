import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { useSession } from '@/composables/useSession'
import { fetchBillingSetup } from '@/data/billingSetup'

const routes = [
	{
		path: '/login',
		name: 'Login',
		component: () => import('@/pages/auth/LoginPage.vue'),
		meta: { public: true },
	},
	{
		path: '/signup',
		name: 'Signup',
		component: () => import('@/pages/auth/SignupPage.vue'),
		meta: { public: true },
	},
	{
		path: '/signup/verify',
		name: 'VerifyEmail',
		component: () => import('@/pages/auth/VerifyEmailPage.vue'),
		meta: { public: true },
	},
	{
		path: '/forgot-password',
		name: 'ForgotPassword',
		component: () => import('@/pages/auth/ForgotPasswordPage.vue'),
		meta: { public: true },
	},
	{
		path: '/onboarding/site',
		name: 'OnboardingSite',
		component: () => import('@/pages/onboarding/SiteNamePage.vue'),
	},
	{
		path: '/onboarding/provisioning/:name',
		name: 'OnboardingProvisioning',
		component: () => import('@/pages/onboarding/SiteReadyPage.vue'),
	},
	// authenticated routes -> AppShell
	{
		path: '/',
		component: () => import('@/layouts/AppShell.vue'),
		children: [
			{ path: '', redirect: '/servers' },
			{
				path: 'home',
				name: 'Home',
				component: () => import('@/pages/home/HomePage.vue'),
				meta: { title: 'Home' },
			},
			{
				path: 'servers',
				name: 'Servers',
				component: () => import('@/pages/servers/ServersPage.vue'),
				meta: { title: 'Servers' },
			},
			{
				path: 'servers/new',
				name: 'NewServer',
				component: () => import('@/pages/servers/NewServerPage.vue'),
				meta: { title: 'New server' },
			},
			// Services are reached directly from the sidebar's Services group; a bare
			// /services falls through to the one service today.
			{ path: 'services', redirect: '/services/llm' },
			{
				path: 'services/:service',
				name: 'ServiceDetail',
				component: () => import('@/pages/services/ServiceDetailPage.vue'),
				meta: { title: 'Services' },
			},
			{
				path: 'billing',
				name: 'Billing',
				component: () => import('@/pages/billing/BillingOverviewPage.vue'),
				meta: { title: 'Billing' },
			},
			{
				path: 'billing/invoices',
				name: 'BillingInvoices',
				component: () => import('@/pages/billing/BillingInvoicesPage.vue'),
				meta: { title: 'Invoices' },
			},
			{
				path: 'billing/limits',
				name: 'SpendingLimits',
				component: () => import('@/pages/billing/SpendingLimitsPage.vue'),
				meta: { title: 'Spending Limits' },
			},
			{
				path: 'notifications',
				name: 'Notifications',
				component: () => import('@/pages/notifications/NotificationsPage.vue'),
				meta: { title: 'Notifications' },
			},
			{
				path: 'settings',
				name: 'Settings',
				component: () => import('@/pages/settings/SettingsPage.vue'),
				meta: { title: 'Settings' },
			},
			{
				path: 'notifications/preferences',
				name: 'NotificationPreferences',
				component: () => import('@/pages/notifications/NotificationPreferencesPage.vue'),
			},
			{ path: 'team', redirect: '/team/members' },
			// Members + roles share one tabbed page; /team/roles is kept as an alias.
			{
				path: 'team/members',
				name: 'Members',
				component: () => import('@/pages/team/AccessPage.vue'),
				meta: { title: 'Team' },
			},
			{ path: 'team/roles', redirect: '/team/members' },
			{
				path: 'team/invitations',
				name: 'TeamInvitations',
				component: () => import('@/pages/team/InvitationsPage.vue'),
				meta: { title: 'Invitations' },
			},
			{
				path: 'team/settings',
				name: 'TeamSettings',
				component: () => import('@/pages/team/TeamSettingsPage.vue'),
				meta: { title: 'Team settings' },
			},
			// Personal invitation inbox + the email deep-link both open the Invitations
			// page on its Received tab.
			{
				path: 'invitations',
				name: 'MyInvitations',
				component: () => import('@/pages/team/InvitationsPage.vue'),
				meta: { title: 'Invitations' },
			},
			{
				path: 'invitations/:name',
				name: 'FocusedInvitation',
				component: () => import('@/pages/team/InvitationsPage.vue'),
				meta: { title: 'Invitations' },
			},
		],
	},
]

export const router = createRouter({
	history: createWebHistory('/dashboard/'),
	routes,
})

// Session state is seeded synchronously from boot data (window.user), so the
// guard can decide without awaiting. Auth transitions (login/logout) do a full
// page reload, which re-boots the SPA with a fresh session — no client revalidation needed.
router.beforeEach((to) => {
	const { isGuest } = useAuth()
	// Seeded with `window.user` (central/www/dashboard.py). A brand-new user has no
	// live site yet, so they belong in the onboarding funnel, not the dashboard.
	const onboardingComplete = window.onboarding_complete ?? false

	if (to.meta.public) {
		if (isGuest.value) return true
		// Logged in but on an auth page — e.g. browser-Back after verifying. Don't dump
		// them into the dashboard mid-onboarding: resume the funnel until it's finished.
		return onboardingComplete ? '/servers' : '/onboarding/site'
	}

	if (isGuest.value) {
		return {
			path: '/login',
			query: { 'redirect-to': `/dashboard${to.fullPath}` },
		}
	}

	// A finished user has no reason to re-enter onboarding.
	if (to.path.startsWith('/onboarding') && onboardingComplete) return '/servers'

	// Warm the billing-profile completeness cache for the active team, non-blocking
	// (mirrors the legacy guard): money-moving actions gate on it via
	// useBillingSetup.requireSetup, but navigation stays open. Never redirects.
	const { activeTeam } = useSession()
	if (activeTeam.value) void fetchBillingSetup(activeTeam.value)

	return true
})
