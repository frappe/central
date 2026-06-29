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
        path: 'servers',
        name: 'Servers',
        component: () => import('@/pages/servers/ServersPage.vue'),
      },
      {
        path: 'servers/new',
        name: 'NewServer',
        component: () => import('@/pages/servers/NewServerPage.vue'),
      },
      {
        path: 'billing',
        name: 'Billing',
        component: () => import('@/pages/billing/BillingOverviewPage.vue'),
      },
      {
        path: 'billing/invoices',
        name: 'BillingInvoices',
        component: () => import('@/pages/billing/BillingInvoicesPage.vue'),
      },
      {
        path: 'billing/limits',
        name: 'SpendingLimits',
        component: () => import('@/pages/billing/SpendingLimitsPage.vue'),
      },
      {
        // Destination the billing-setup gate (useBillingSetup.requireSetup)
        // diverts incomplete-profile teams to. Filled out in #68.
        path: 'billing/onboarding',
        name: 'BillingOnboarding',
        component: () => import('@/pages/billing/BillingOnboardingPage.vue'),
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
    return { path: '/login', query: { 'redirect-to': `/dashboard${to.fullPath}` } }
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
