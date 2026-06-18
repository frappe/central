import { createRouter, createWebHistory } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import GroupGate from '@/components/GroupGate.vue'

// The SPA is mounted under /dashboard (central/hooks.py website_route_rules).
const routes = [
  {
    path: '/',
    component: AppLayout,
    children: [
      { path: '', redirect: '/billing' },

      // First-run billing setup wizard — rendered inside the shell. Navigation
      // stays open; money-moving actions divert here via requireSetup() until the
      // billing profile is complete, passing a ?redirect= back to where they were.
      { path: 'onboarding', name: 'Onboarding', component: () => import('@/pages/Onboarding.vue') },

      {
        path: 'billing',
        component: GroupGate,
        props: { capability: 'billing:view', roles: 'Owner or Billing' },
        children: [
          { path: '', name: 'Overview', component: () => import('@/pages/billing/Overview.vue') },
          { path: 'invoices', name: 'Invoices', component: () => import('@/pages/billing/Invoices.vue') },
          { path: 'credits', name: 'Credits', component: () => import('@/pages/billing/Credits.vue') },
          { path: 'subscriptions', name: 'Subscriptions', component: () => import('@/pages/billing/Subscriptions.vue') },
        ],
      },

      {
        path: 'settings',
        component: GroupGate,
        props: { capability: 'billing:view', roles: 'Owner or Billing' },
        children: [
          { path: '', redirect: '/settings/address' },
          { path: 'address', name: 'Address', component: () => import('@/pages/billing/Settings.vue') },
          { path: 'methods', name: 'PaymentMethods', component: () => import('@/pages/billing/PaymentMethods.vue') },
          { path: 'notifications', name: 'Notifications', component: () => import('@/pages/billing/Notifications.vue') },
        ],
      },

      {
        path: 'team',
        component: GroupGate,
        props: { requireMember: true, roles: 'any team member' },
        children: [
          { path: '', redirect: '/team/members' },
          { path: 'members', name: 'Members', component: () => import('@/pages/team/Members.vue') },
          { path: 'roles/new', name: 'NewRole', component: () => import('@/pages/team/RoleBuilder.vue') },
          { path: 'trust-tier', name: 'TrustTier', component: () => import('@/pages/team/TrustTier.vue') },
        ],
      },

      {
        path: 'atlas',
        component: GroupGate,
        props: { capability: 'vm:view', roles: 'Developer, Admin or Owner' },
        children: [
          { path: '', name: 'AtlasRegistry', component: () => import('@/pages/atlas/Registry.vue') },
          { path: 'vms', name: 'AtlasVMs', component: () => import('@/pages/atlas/VirtualMachines.vue') },
          { path: 'region', name: 'AtlasRegion', component: () => import('@/pages/atlas/Region.vue') },
          { path: 'access', name: 'AtlasAccess', component: () => import('@/pages/atlas/AccessRequests.vue') },
        ],
      },
    ],
  },
]

export const router = createRouter({
  history: createWebHistory('/dashboard/'),
  routes,
})

// Navigation is open regardless of billing-profile completeness — a team with an
// incomplete profile can browse every tab. The profile is only enforced at the
// point of a money-moving action (top-up, credits, payment method), where
// useBillingSetup().requireSetup() diverts to /onboarding. Here we just warm the
// shared setup cache for the active team so those pages render their state without
// a flash. Identity is resolved first so we key on the active team, not a default.
router.beforeEach(async () => {
  await whoReady
  const { currentTeam } = useTeam()
  fetchBillingSetup(currentTeam.value) // non-blocking: warm cache, never redirect
  return true
})
