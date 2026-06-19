/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

// Boot data injected by central/www/console.py (see jinjaBootData in vite.config).
// frappe-ui's request layer reads window.csrf_token for write (POST) calls.
interface Window {
  csrf_token?: string
  user?: string
}
