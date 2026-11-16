import type { LocationQuery, LocationQueryRaw } from 'vue-router'
import { queryString } from '@/lib/auth'

const DEFAULT_DASHBOARD = '/dashboard/servers'
const PRODUCT_ONBOARDING = '/dashboard/onboarding/site'
// Central's mailbox sign-in callback sends a logged-out browser here to log in, then back to it
const EMAIL_OAUTH_CALLBACK = '/api/method/central.api.email_oauth.callback?'

/** Where to land once signed in: the requested page, the product onboarding, or the console. */
export function signInDestination(query: LocationQuery): string {
	const requested = dashboardPath(queryString(query['redirect-to']))
	if (requested) return requested
	const product = queryString(query.product)
	if (!product) return DEFAULT_DASHBOARD
	const returnTo = queryString(query.return_to)
	const onboarding = new URLSearchParams({ product })
	if (returnTo) onboarding.set('return_to', returnTo)
	return `${PRODUCT_ONBOARDING}?${onboarding}`
}

/** The product onboarding route when sign-in lands there, so the console carries on in place. */
export function productOnboarding(
	query: LocationQuery,
): { path: string; query: LocationQueryRaw } | null {
	const product = queryString(query.product)
	if (!product || queryString(query['redirect-to'])) return null
	return { path: '/onboarding/site', query: carriedQuery(query) }
}

/** The intent that must survive every step between the auth pages. `return_to` is the AI app
 * a connector sign in goes back to, which Central checks against the product's hosts. */
export function carriedQuery(query: LocationQuery): LocationQueryRaw {
	const carried: LocationQueryRaw = {}
	for (const key of ['product', 'redirect-to', 'return_to']) {
		const value = queryString(query[key])
		if (value) carried[key] = value
	}
	return carried
}

function dashboardPath(value: string): string | null {
	if (!value) return null

	const path = sameOriginPath(value)
	if (path?.startsWith(EMAIL_OAUTH_CALLBACK)) return path
	if (path === '/dashboard') return DEFAULT_DASHBOARD
	if (!path?.startsWith('/dashboard/')) return null
	if (/^\/dashboard\/(login|signup|verify)\b/.test(path)) return null
	return path
}

function sameOriginPath(value: string): string | null {
	try {
		const url = new URL(value, window.location.origin)
		if (url.origin !== window.location.origin) return null
		return `${url.pathname}${url.search}${url.hash}`
	} catch {
		return null
	}
}
