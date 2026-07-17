import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import frappeui from 'frappe-ui/vite'
import path from 'path'

// Primary Central frontend.
export default defineConfig({
	plugins: [
		frappeui({
			frontendRoute: '/dashboard',
			frappeProxy: true,
			jinjaBootData: true,
			buildConfig: {
				outDir: path.resolve(__dirname, '../central/public/dashboard'),
				baseUrl: '/assets/central/dashboard/',
				indexHtmlPath: path.resolve(__dirname, '../central/www/dashboard.html'),
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
