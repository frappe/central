import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '@/composables/useAuth'

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
    path: '/signup/check-email',
    name: 'CheckEmail',
    component: () => import('@/pages/auth/CheckEmailPage.vue'),
    meta: { public: true },
  },
  {
    path: '/forgot-password',
    name: 'ForgotPassword',
    component: () => import('@/pages/auth/ForgotPasswordPage.vue'),
    meta: { public: true },
  },
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

  if (to.meta.public) {
    return isGuest.value ? true : '/servers'
  }

  if (isGuest.value) {
    return { path: '/login', query: { 'redirect-to': `/dashboard${to.fullPath}` } }
  }

  return true
})
