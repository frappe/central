const erpProduction = ({ servers }) => `/servers/${servers['erp-production']}`

/** Shows the setup dialog of a new team, without a change to the demo team. */
async function openOnboarding(page) {
	await page.route((url) => url.pathname.endsWith('/central.api.identity.my_teams'), async (route) => {
		const body = await (await route.fetch()).json()
		for (const team of body.data) team.onboarding = ['invite', 'billing', 'start']
		await route.fulfill({ json: body })
	})
	await page.route((url) => url.pathname.endsWith('/central.api.teams.set_onboarding_step'), (route) =>
		route.fulfill({ json: { data: route.request().postDataJSON() } }),
	)

	// Stripe keeps the network busy, so the page would never settle.
	await page.route(/stripe\.(com|network)/, (route) => route.abort())

	await page.reload()
	await page.getByRole('button', { name: 'Skip', exact: true }).click()
	await page.getByRole('button', { name: 'Back' }).waitFor()
}

export default [
	{ name: 'get-started/onboarding', path: '/servers', setup: openOnboarding, target: '[role="dialog"]' },
	{ name: 'get-started/console', path: '/servers' },
	{
		name: 'get-started/team-switcher',
		path: '/servers',
		async setup(page) {
			await page.getByText('Contrail Coffee', { exact: true }).first().click()
			await page.mouse.move(700, 700)
		},
	},
	{
		name: 'get-started/search',
		path: '/servers',
		setup: (page) => page.keyboard.press('Meta+K'),
	},
	{
		name: 'get-started/notifications',
		path: '/servers',
		setup: (page) => page.getByText('Notifications', { exact: true }).first().click(),
	},
	{
		name: 'get-started/user-menu',
		path: '/servers',
		setup: (page) => page.getByText('Zara Quill', { exact: true }).first().click(),
	},
	{ name: 'get-started/server-running', path: erpProduction },
	{ name: 'get-started/server-header', path: erpProduction, target: 'header:has(h1)' },
]
