import type { LocationQuery } from 'vue-router'
import { queryString } from '@/lib/auth'

/** How a visitor first arrived. The team created at signup keeps it. */
export type FirstTouch = {
	utm_source?: string
	utm_medium?: string
	utm_campaign?: string
	referrer?: string
	product?: string
}

const STORAGE_KEY = 'central:signup-first-touch'
const QUERY_KEYS = [
	'utm_source',
	'utm_medium',
	'utm_campaign',
	'product',
] as const

/** Remember the first arrival only. A later visit in the same browser keeps it. */
export function rememberFirstTouch(query: LocationQuery) {
	if (readFirstTouch()) return

	const touch: FirstTouch = {}
	for (const key of QUERY_KEYS) {
		const value = queryString(query[key])
		if (value) touch[key] = value
	}
	const referrer = externalReferrer()
	if (referrer) touch.referrer = referrer
	if (!Object.keys(touch).length) return

	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(touch))
	} catch {
		// Storage can be blocked. The signup goes on without attribution.
	}
}

export function readFirstTouch(): FirstTouch | null {
	try {
		const saved = localStorage.getItem(STORAGE_KEY)
		return saved ? (JSON.parse(saved) as FirstTouch) : null
	} catch {
		return null
	}
}

export function forgetFirstTouch() {
	try {
		localStorage.removeItem(STORAGE_KEY)
	} catch {
		// Nothing to forget when storage is blocked.
	}
}

function externalReferrer(): string | null {
	if (!document.referrer) return null
	try {
		const origin = new URL(document.referrer).origin
		return origin === window.location.origin ? null : document.referrer
	} catch {
		return null
	}
}
