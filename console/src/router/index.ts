import { createRouter, createWebHistory } from 'vue-router'
import { sessionReady } from '@/composables/useSession'

// The SPA is served under /console (central/hooks.py website_route_rules →
// www/console). Only the Servers surface exists for now; the structure leaves
// room for the rest of the console to grow alongside it.
const routes = [
  { path: '/', redirect: '/servers' },
  {
    path: '/servers',
    name: 'Servers',
    component: () => import('@/pages/servers/ServersPage.vue'),
  },
  {
    path: '/servers/new',
    name: 'NewServer',
    component: () => import('@/pages/servers/NewServerPage.vue'),
  },
]

export const router = createRouter({
  history: createWebHistory('/console/'),
  routes,
})

// Identity first — team-scoped atlas reads await my_teams so they always carry
// ?team=… (see central.atlas._resolve_team).
router.beforeEach(async () => {
  await sessionReady
  return true
})
