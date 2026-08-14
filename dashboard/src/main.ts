import { FrappeUI } from 'frappe-ui'
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

const host = window.location.hostname
const siteName = import.meta.env.DEV ? host : window.site_name
const socketioPort = window.socketio_port || 9000
const port = window.location.port ? `:${socketioPort}` : ''
const protocol = port ? 'http' : 'https'
app.config.globalProperties.$socket = io(
	`${protocol}://${host}${port}/${siteName}`,
	{ withCredentials: true },
)

router.isReady().then(() => app.mount('#app'))
