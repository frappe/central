/// <reference types="vite/client" />

/** The bench's Socket.IO port, compiled in by vite.config.ts. Null when no bench config
 *  was found at build time. */
declare const __SOCKETIO_PORT__: number | null

declare module '*.vue' {
	import type { DefineComponent } from 'vue'

	const component: DefineComponent<{}, {}, any>
	export default component
}

// Boot data injected by central/www/dashboard.py (see jinjaBootData in vite.config).
// frappe-ui's request layer reads window.csrf_token for write (POST) calls.
interface Window {
	csrf_token?: string
	user?: string
	user_type?: string
	provider_logins?: import('@/types/api').ProviderLogin[]
	site_name?: string
	socketio_port?: number
	onboarding_complete?: boolean
	features?: {
		addons?: boolean
		llm?: boolean
		pdf?: boolean
		email?: boolean
		storage?: boolean
	}
}
