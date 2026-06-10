import { createRouter, createWebHistory } from 'vue-router'

// The SPA is mounted under /dashboard (see central/hooks.py website_route_rules).
const routes = [
  {
    path: '/',
    redirect: '/billing',
  },
]

export const router = createRouter({
  history: createWebHistory('/dashboard/'),
  routes,
})
