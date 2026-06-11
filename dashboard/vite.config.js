import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import frappeui from 'frappe-ui/vite'
import path from 'path'

// Built assets are served by Frappe from central/public/dashboard at
// /assets/central/dashboard/, and the SPA index is mounted at /dashboard
// (see central/hooks.py website_route_rules).
export default defineConfig({
  base: '/assets/central/dashboard/',
  plugins: [
    frappeui({
      // We run inside the Central bench, so keep the Frappe-specific helpers:
      // frappeProxy auto-proxies /api to the local site during `yarn dev`.
      frappeProxy: true,
      jinjaBootData: true,
      buildConfig: false,
    }),
    vue(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  build: {
    outDir: path.resolve(__dirname, '../central/public/dashboard'),
    emptyOutDir: true,
    target: 'es2015',
    sourcemap: true,
    manifest: true,
  },
  optimizeDeps: {
    exclude: ['frappe-ui'],
    include: [
      'feather-icons',
      'tippy.js',
      'showdown',
      'engine.io-client',
      'socket.io-client',
      'debug',
    ],
  },
})
