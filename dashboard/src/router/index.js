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

      {
        path: 'billing',
        component: GroupGate,
        props: { capability: 'billing:view', roles: 'Owner or Billing' },
        children: [
          { path: '', name: 'Overview', component: () => import('@/pages/billing/Overview.vue') },
          { path: 'invoices', name: 'Invoices', component: () => import('@/pages/billing/Invoices.vue') },
          { path: 'methods', name: 'PaymentMethods', component: () => import('@/pages/billing/PaymentMethods.vue') },
          { path: 'credits', name: 'Credits', component: () => import('@/pages/billing/Credits.vue') },
          { path: 'payments', name: 'PaymentHistory', component: () => import('@/pages/billing/PaymentHistory.vue') },
          { path: 'subscriptions', name: 'Subscriptions', component: () => import('@/pages/billing/Subscriptions.vue') },
          { path: 'notifications', name: 'Notifications', component: () => import('@/pages/billing/Notifications.vue') },
          { path: 'settings', name: 'Settings', component: () => import('@/pages/billing/Settings.vue') },
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
