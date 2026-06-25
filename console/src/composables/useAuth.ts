import { computed, readonly, ref } from 'vue'
import { frappeRequest } from 'frappe-ui'
import type { ProviderLogin } from '@/types'

// Auth for the console/dashboard app a single reactive `currentUser` plus `login` / `logout` / `updateCurrentUser` that wrap
// Frappe's native endpoints. Module-level singletons so every screen shares one session state.
// Boot data (window.user, injected by central/www/dashboard.py) seeds the initial value, so the first paint already knows who is signed in.

export interface PasswordCredentials {
  username: string
  password: string
}

/** Second factor: the login endpoint returns a `tmp_id` to replay with the OTP. */
export interface OtpCredentials {
  tmp_id: string
  otp: string
}

export type AuthCredentials = PasswordCredentials | OtpCredentials

export interface LoginResponse {
  message?: string
  home_page?: string
  redirect_to?: string
  tmp_id?: string
  verification?: {
    method: 'Email' | 'SMS' | 'OTP App'
    setup: boolean
    prompt?: string
  }
}

const currentUser = ref<string | null>(initialUser())
const providerLogins = ref<ProviderLogin[]>(window.provider_logins ?? [])
const isLoading = ref(false)
const isValidating = ref(false)
const error = ref<unknown>(null)

export function useAuth() {
  return {
    currentUser: readonly(currentUser),
    isLoggedIn: computed(() => currentUser.value !== null),
    isGuest: computed(() => currentUser.value === null),
    providerLogins: readonly(providerLogins),
    isLoading: readonly(isLoading),
    isValidating: readonly(isValidating),
    error: readonly(error),
    login,
    logout,
    updateCurrentUser,
    getUserCookie,
  }
}

async function login(credentials: AuthCredentials): Promise<LoginResponse> {
  error.value = null
  try {
    const response = (await frappeRequest({
      url: '/api/method/login',
      method: 'POST',
      params: loginParams(credentials),
    })) as LoginResponse

    // No `verification` means the password (or OTP) round-trip logged us in:
    // "Logged In" for desk users, "No App" for the Website Users Central creates.
    if (!response.verification) getUserCookie()
    return response
  } catch (exception) {
    error.value = exception
    throw exception
  }
}

async function logout(): Promise<void> {
  error.value = null
  try {
    await frappeRequest({ url: '/api/method/logout', method: 'POST' })
    currentUser.value = null
  } catch (exception) {
    error.value = exception
    throw exception
  }
}

/** Revalidate against the server — the source of truth when the cookie may be stale. */
async function updateCurrentUser(): Promise<string | null> {
  isValidating.value = true
  isLoading.value = currentUser.value === null
  error.value = null
  try {
    const user = (await frappeRequest({
      url: '/api/method/frappe.auth.get_logged_user',
      method: 'GET',
    })) as string
    currentUser.value = user && user !== 'Guest' ? user : null
    return currentUser.value
  } catch (exception) {
    currentUser.value = null
    error.value = exception
    return null
  } finally {
    isLoading.value = false
    isValidating.value = false
  }
}

/** Sync `currentUser` from the `user_id` cookie Frappe sets on login. */
function getUserCookie(): string | null {
  currentUser.value = readUserCookie()
  return currentUser.value
}

/** Initial session, resolved synchronously so the first paint and the router
 *  guard both know who is signed in. `window.user` is injected by the
 *  server-rendered page in production; in dev the Vite plugin does NOT inject
 *  boot data, so we fall back to the `user_id` cookie Frappe sets on login
 *  (forwarded by the dev proxy and not HttpOnly, so it's readable here). */
function initialUser(): string | null {
  return bootUser() ?? readUserCookie()
}

function bootUser(): string | null {
  return window.user && window.user !== 'Guest' ? window.user : null
}

function readUserCookie(): string | null {
  const cookie = document.cookie
    .split(';')
    .find((value) => value.trim().startsWith('user_id='))
  const user = cookie ? decodeURIComponent(cookie.split('=').slice(1).join('=')) : null
  return user && user !== 'Guest' ? user : null
}

function loginParams(credentials: AuthCredentials): Record<string, string> {
  if ('username' in credentials) {
    return { usr: credentials.username, pwd: credentials.password }
  }
  return { tmp_id: credentials.tmp_id, otp: credentials.otp }
}
