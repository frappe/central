/// <reference types="vite/client" />
/// <reference types="unplugin-icons/types/vue" />

/** The bench's Socket.IO port, compiled in by vite.config.ts. Null when no bench config
 *  was found at build time. */
declare const __SOCKETIO_PORT__: number | null

declare module '*.vue' {
	import type { DefineComponent } from 'vue'

	const component: DefineComponent<Record<string, unknown>>
	export default component
}

// Boot data injected by central/www/dashboard.py (see jinjaBootData in vite.config).
// frappe-ui's request layer reads window.csrf_token for write (POST) calls.
interface Window {
	csrf_token?: string
	user?: string
	user_type?: string
	site_name?: string
	socketio_port?: number
	/** Site timezone Frappe stores naive datetimes in. See dashboard.py. */
	system_timezone?: string
	/** Days a new team invitation stays open, from Central Settings. */
	invitation_expiry_days?: number
	/** The reader's language, such as "de". */
	lang?: string
	/** Changes when a translation changes, so the cached catalog URL changes. See lib/translate.ts. */
	translations_version?: string
	/** Upload limit in bytes, from System Settings. */
	max_file_size?: number
	/** Help menu links from Central Settings. Null when an operator left one empty. */
	help_links?: {
		support_ticket_url?: string | null
		feedback_url?: string | null
		/** True when the Helpdesk API is configured, so the console opens its own dialog. */
		in_app_tickets?: boolean
		/** True when the dialog searches help articles before it offers a ticket. */
		articles_enabled?: boolean
	}
	features?: {
		addons?: boolean
		storage?: boolean
		llm?: boolean
		public_ipv4?: boolean
		public_ipv6?: boolean
		firewall?: boolean
	}
}
