import type { LoginResponse } from '@/composables/useAuth'

const DEFAULT_DASHBOARD = '/dashboard/servers'

export function loginDestination(
	response: LoginResponse,
	requestedPath?: unknown,
): string {
	if (response.message === 'Password Reset' && response.redirect_to) {
		return sameOriginPath(response.redirect_to, '/update-password')
	}

	return (
		dashboardPath(requestedPath) ??
		dashboardPath(response.redirect_to) ??
		dashboardPath(response.home_page) ??
		DEFAULT_DASHBOARD
	)
}

function dashboardPath(value: unknown): string | null {
	if (typeof value !== 'string' || !value) return null

	const path = sameOriginPath(value)
	if (path === '/dashboard') return DEFAULT_DASHBOARD
	if (!path.startsWith('/dashboard/')) return null
	if (path === '/dashboard/login' || path.startsWith('/dashboard/signup'))
		return null
	return path
}

function sameOriginPath(value: string, fallback = DEFAULT_DASHBOARD): string {
	try {
		const url = new URL(value, window.location.origin)
		return url.origin === window.location.origin
			? `${url.pathname}${url.search}${url.hash}`
			: fallback
	} catch {
		return fallback
	}
}
