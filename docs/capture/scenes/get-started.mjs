const erpProduction = ({ servers }) => `/servers/${servers['erp-production']}`

export default [
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
