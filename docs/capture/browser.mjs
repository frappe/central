import { chromium } from '@playwright/test'
import { atlasFixtures, pilotRoutes } from './fixtures.mjs'

export const BASE_URL = process.env.DOCS_DEMO_URL || 'http://docs.localhost:8010'
export const PILOT_URL = process.env.DOCS_PILOT_URL || 'http://localhost:7003'
export const VIEWPORT = { width: 1280, height: 800 }

/** Where each app lives and how a capture signs in to it. */
const APPS = {
	console: {
		home: `${BASE_URL}/dashboard`,
		async signIn(context) {
			const response = await context.request.post(`${BASE_URL}/api/method/login`, {
				form: { usr: 'zara@contrail.example', pwd: 'docs@2026' },
			})
			if (!response.ok()) throw new Error(`Console sign-in failed with HTTP ${response.status()}. Run the seed first.`)
			await answerFromFixtures(context)
		},
	},
	pilot: {
		home: PILOT_URL,
		async signIn(context) {
			const response = await context.request.post(`${PILOT_URL}/api/v1/auth/session`, { data: { password: 'Docs@2026' } })
			if (response.status() === 429) throw new Error('Pilot allows 5 sign-ins a minute. Wait a minute, then run again.')
			if (!response.ok()) throw new Error(`Pilot sign-in failed with HTTP ${response.status()}. Start the docs-pilot bench first.`)
			for (const { matches, respond } of pilotRoutes) {
				await context.route(matches, (route) =>
					route.request().method() === 'GET' ? respond(route, new URL(route.request().url())) : route.continue(),
				)
			}
		},
	},
}

// Steady screenshots: no caret blink, no scrollbars, no transitions mid-capture.
const STEADY_CSS = `
	*, *::before, *::after { caret-color: transparent !important; }
	::-webkit-scrollbar { display: none; }
	html { scrollbar-width: none; }
`

/** Opens a signed-in page of `app` (`console` or `pilot`) for one theme. */
export async function openApp(theme, { app = 'console', scale = 2, motion = false } = {}) {
	const browser = await chromium.launch()
	const context = await browser.newContext({
		viewport: VIEWPORT,
		deviceScaleFactor: scale,
		colorScheme: theme,
		// Still screenshots need no motion. A studio recording keeps the app's own transitions.
		reducedMotion: motion ? 'no-preference' : 'reduce',
	})
	await APPS[app].signIn(context)

	await context.addInitScript((value) => localStorage.setItem('theme', value), theme)
	await context.addInitScript((css) => {
		addEventListener('DOMContentLoaded', () => {
			const style = document.createElement('style')
			style.textContent = css
			document.head.append(style)
		})
	}, STEADY_CSS)

	const page = await context.newPage()
	return { browser, context, page }
}

/** The console reads that need a live region answer from fixtures. The v2 API wraps the answer as `data`. */
async function answerFromFixtures(context) {
	for (const [method, answer] of Object.entries(atlasFixtures())) {
		await context.route(
			(url) => url.pathname.endsWith(`/method/${method}`),
			(route) => {
				const url = new URL(route.request().url())
				const key = url.pathname.startsWith('/api/v2/') ? 'data' : 'message'
				return route.fulfill({ json: { [key]: answer(url) } })
			},
		)
	}
}

/** Navigates inside an app and waits until data has loaded and the page is still. */
export async function visit(page, path, app = 'console') {
	await page.goto(`${APPS[app].home}${path}`, { waitUntil: 'networkidle' })
	await settle(page)
}

export async function settle(page, milliseconds = 600) {
	await page.waitForLoadState('networkidle')
	await page.evaluate(() => document.fonts.ready)
	await page.waitForTimeout(milliseconds)
}
