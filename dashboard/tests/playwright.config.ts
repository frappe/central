import { fileURLToPath } from 'node:url'
import { defineConfig } from '@playwright/test'

export default defineConfig({
	testDir: '.',
	testMatch: '*.spec.ts',
	workers: 1,
	use: {
		channel: process.env.PLAYWRIGHT_CHANNEL,
		baseURL: 'http://127.0.0.1:5177',
		screenshot: 'only-on-failure',
		trace: 'retain-on-failure',
	},
	outputDir: '/tmp/central-server-controls-results',
	webServer: {
		command: 'node node_modules/vite/bin/vite.js --config tests/vite.config.ts',
		cwd: fileURLToPath(new URL('..', import.meta.url)),
		url: 'http://127.0.0.1:5177/tests/server-controls.html',
		reuseExistingServer: !process.env.CI,
	},
})
