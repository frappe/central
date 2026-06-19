import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import frappeui from 'frappe-ui/vite'
import path from 'path'

// Second Central frontend (TypeScript). Coexists with the legacy JS `dashboard`
// app: this one builds to its own asset dir and serves under `/console`, leaving
// `/dashboard` completely untouched. See central/www/console.py + hooks.py.
export default defineConfig({
  plugins: [
    frappeui({
      frontendRoute: '/console',
      frappeProxy: true,
      jinjaBootData: true,
      buildConfig: {
        outDir: path.resolve(__dirname, '../central/public/console'),
        baseUrl: '/assets/central/console/',
        indexHtmlPath: path.resolve(__dirname, '../central/www/console.html'),
      },
    }),
    vue(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  build: {
    outDir: path.resolve(__dirname, '../central/public/console'),
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
