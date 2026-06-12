import { createApp } from 'vue'
import { FrappeUI } from 'frappe-ui'
import { router } from './router'
import './style.css'
import App from './App.vue'

const app = createApp(App)
app.use(router)
app.use(FrappeUI)

// Mount only after the initial guarded navigation resolves, so a hard refresh
// paints the correct route (e.g. onboarding) instead of briefly showing the
// target route before the async billing-setup guard redirects.
router.isReady().then(() => app.mount('#app'))
