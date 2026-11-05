import { fileURLToPath } from 'node:url'
import vue from '@vitejs/plugin-vue'
import frappeui from 'frappe-ui/vite'
import { defineConfig } from 'vite'

export default defineConfig({
	root: fileURLToPath(new URL('..', import.meta.url)),
	plugins: [
		frappeui({ frappeProxy: false, jinjaBootData: false, buildConfig: false }),
		vue(),
	],
	resolve: {
		alias: { '@': fileURLToPath(new URL('../src', import.meta.url)) },
	},
	server: { host: '127.0.0.1', port: 5177, strictPort: true },
})
