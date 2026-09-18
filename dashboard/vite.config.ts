import vue from '@vitejs/plugin-vue'
import frappeui from 'frappe-ui/vite'
import fs from 'fs'
import path from 'path'
import { defineConfig } from 'vite'

/** The bench's Socket.IO port, read from `sites/common_site_config.json` at build time.
 *
 *  Frappe puts `window.socketio_port` on the page only when the bench serves it in
 *  developer mode. Under `vite dev`, and on any build where that boot key is missing,
 *  the browser has nothing to go on. A guessed port is the worst outcome: it fails as a
 *  refused connection, live updates stop, and nothing else says why. Reading the bench
 *  config here gives the page the real answer instead. */
function benchSocketioPort(): number | null {
	let directory = __dirname
	while (directory !== path.dirname(directory)) {
		const config = path.join(directory, 'sites', 'common_site_config.json')
		if (fs.existsSync(config))
			return JSON.parse(fs.readFileSync(config, 'utf8')).socketio_port ?? null
		directory = path.dirname(directory)
	}
	return null
}

// Primary Central frontend.
export default defineConfig({
	define: {
		__SOCKETIO_PORT__: JSON.stringify(benchSocketioPort()),
	},
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
