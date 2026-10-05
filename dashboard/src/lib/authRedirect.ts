import type { LocationQuery, LocationQueryRaw } from 'vue-router'
import { queryString } from '@/lib/auth'

const DEFAULT_DASHBOARD = '/dashboard/servers'
const PRODUCT_ONBOARDING = '/dashboard/onboarding/site'

/** Where to land once signed in: the requested page, the product onboarding, or the console. */
export function signInDestination(query: LocationQuery): string {
	const requested = dashboardPath(queryString(query['redirect-to']))
	if (requested) return requested
	const product = queryString(query.product)
	if (!product) return DEFAULT_DASHBOARD
	return `${PRODUCT_ONBOARDING}?${new URLSearchParams({ product })}`
}

/** The intent that must survive every step between the auth pages. */
export function carriedQuery(query: LocationQuery): LocationQueryRaw {
	const carried: LocationQueryRaw = {}
	for (const key of ['product', 'redirect-to']) {
		const value = queryString(query[key])
		if (value) carried[key] = value
	}
	return carried
}

function dashboardPath(value: string): string | null {
	if (!value) return null

	const path = sameOriginPath(value)
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
