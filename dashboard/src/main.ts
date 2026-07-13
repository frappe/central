import { createApp } from 'vue'
import { FrappeUI } from 'frappe-ui'
import { router } from '@/router'
import App from '@/App.vue'
import { useTheme } from '@/composables/useTheme'
import './style.css'

// Apply the stored (or default light) theme before the app mounts.
useTheme()

// The new data-fetching composables (useCall/useList) read window.csrf_token —
// injected by central/www/dashboard.py — and POST relative to the served origin,
// so no extra request config is needed beyond the FrappeUI plugin.
const app = createApp(App)
app.use(router)
app.use(FrappeUI, {
  socketio: window.socketio_port ? { port: window.socketio_port } : true,
})

router.isReady().then(() => app.mount('#app'))
