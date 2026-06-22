import { createApp } from 'vue'
import { FrappeUI } from 'frappe-ui'
import { router } from '@/router'
import App from '@/App.vue'
import './style.css'

// The new data-fetching composables (useCall/useList) read window.csrf_token —
// injected by central/www/dashboard.py — and POST relative to the served origin,
// so no extra request config is needed beyond the FrappeUI plugin.
const app = createApp(App)
app.use(router)
app.use(FrappeUI)

router.isReady().then(() => app.mount('#app'))
