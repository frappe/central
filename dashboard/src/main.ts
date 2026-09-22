import { FrappeUI, setConfig } from 'frappe-ui'
import { io } from 'socket.io-client'
import { createApp } from 'vue'
import App from '@/App.vue'
import { router } from '@/router'
import './style.css'

// The new data-fetching composables (useCall/useList) read window.csrf_token —
// injected by central/www/dashboard.py — and POST relative to the served origin,
// so no extra request config is needed beyond the FrappeUI plugin.
const app = createApp(App)
app.use(router)
app.use(FrappeUI)

if (window.system_timezone) setConfig('systemTimezone', window.system_timezone)

// Where Socket.IO listens: what Frappe put on the page when it served it, else the
// bench's own `socketio_port`, compiled in by vite.config.ts. Never a guess — a wrong
// port looks exactly like a working app whose live updates silently never arrive.
const socketioPort = window.socketio_port ?? __SOCKETIO_PORT__
if (!socketioPort)
	console.warn(
		'No Socket.IO port in the page boot or the bench config. Live updates are off.',
	)

const host = window.location.hostname
const siteName = import.meta.env.DEV ? host : window.site_name
const port = window.location.port ? `:${socketioPort}` : ''
const protocol = port ? 'http' : 'https'
app.config.globalProperties.$socket = io(
	`${protocol}://${host}${port}/${siteName}`,
	{ withCredentials: true },
)

router.isReady().then(() => app.mount('#app'))
