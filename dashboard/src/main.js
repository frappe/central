import { createApp } from 'vue'
import { FrappeUI } from 'frappe-ui'
import { router } from './router'
import './style.css'
import App from './App.vue'

const app = createApp(App)
app.use(router)
app.use(FrappeUI)
app.mount('#app')
