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

// Under `yarn dev` nothing server-renders the page, so the token never lands
// and Frappe rejects POSTs once the session has one minted (CSRFTokenError).
// Pull it from the proxied desk page before mounting; production is untouched.
async function ensureCsrfToken(): Promise<void> {
  if (!import.meta.env.DEV || window.csrf_token) return
  try {
    const html = await (await fetch('/app', { headers: { Accept: 'text/html' } })).text()
    window.csrf_token = html.match(/frappe\.csrf_token\s*=\s*"(\w+)"/)?.[1]
  } catch {
    // Logged out or proxy down — POSTs will surface their own errors.
  }
}

Promise.all([router.isReady(), ensureCsrfToken()]).then(() => app.mount('#app'))
