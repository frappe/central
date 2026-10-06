import { frappeRequest } from 'frappe-ui'
import { computed, readonly, ref } from 'vue'

// The console's one reactive `currentUser` and logout. Module-level state is shared by every screen.
// Boot data (window.user, injected by central/www/dashboard.py) seeds the initial value, so the first paint already knows who is signed in.

const currentUser = ref<string | null>(initialUser())

export function useAuth() {
	return {
		currentUser: readonly(currentUser),
		isLoggedIn: computed(() => currentUser.value !== null),
		isGuest: computed(() => currentUser.value === null),
		logout,
	}
}

async function logout(): Promise<void> {
	await frappeRequest({ url: '/api/method/logout', method: 'POST' })
	currentUser.value = null
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
	const user = cookie
		? decodeURIComponent(cookie.split('=').slice(1).join('='))
		: null
	return user && user !== 'Guest' ? user : null
}
