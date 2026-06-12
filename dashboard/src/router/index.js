import { createRouter, createWebHistory } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import GroupGate from '@/components/GroupGate.vue'
import { fetchBillingSetup } from '@/data/billingSetup'
import { useTeam, whoReady } from '@/composables/useTeam'

// The SPA is mounted under /dashboard (central/hooks.py website_route_rules).
const routes = [
  {
    path: '/',
    component: AppLayout,
    children: [
      { path: '', redirect: '/billing' },

      // First-run billing setup — rendered inside the shell (sidebar stays, its
      // billing/settings options stay locked until the profile is complete).
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

// Onboarding gate. Until the billing profile is complete, EVERY route funnels to
// /onboarding — any click or refresh lands there and nowhere else. A set-up team
// is conversely kept off /onboarding. The check is awaited before the route paints
// (and the app mounts only after router.isReady()), so a hard refresh is
// deterministic and never flashes onboarding away. Cached → one request per
// session (invalidated on save). Fail-open: if the check errors, navigation
// proceeds rather than trapping the user.
router.beforeEach(async (to) => {
  // Resolve identity first so we gate on the active team, not an empty/default one.
  await whoReady
  const { currentTeam } = useTeam()
  const setup = await fetchBillingSetup(currentTeam.value)
  const incomplete = setup && setup.complete === false

  if (to.path === '/onboarding') {
    // A set-up team has no business on onboarding — send it on to its target.
    return incomplete ? true : to.query.redirect || '/billing'
  }
  return incomplete ? { path: '/onboarding', query: { redirect: to.fullPath } } : true
})
