const serverPath = (title, tab = '') => ({ servers }) => `/servers/${servers[title]}${tab ? `/${tab}` : ''}`
const section = (title) => `section:has(> header h2:text-is("${title}"))`

// The plan list reads the image's disk size from the region. The demo has no live region, so
// the scene answers with the team's billing catalog, which is the same list without that filter.
async function answerPlansFromCatalog(page) {
	await page.route(
		(url) => url.pathname.endsWith('/method/central.api.images.eligible_plans'),
		async (route) => {
			const url = new URL(route.request().url())
			const query = new URLSearchParams({ team: url.searchParams.get('team'), cluster: url.searchParams.get('region') })
			const catalog = url.pathname.replace('central.api.images.eligible_plans', 'central.billing.api.dashboard.catalog.get_eligible_plans')
			const response = await route.fetch({ url: `${url.origin}${catalog}?${query}`, method: 'GET' })
			const body = await response.json()
			body.data.image_id = url.searchParams.get('image_id') || ''
			await route.fulfill({ json: body })
		},
	)
	await page.reload({ waitUntil: 'networkidle' })
}

export default [
	{ name: 'servers/list', path: '/servers' },
	{ name: 'servers/overview', path: serverPath('erp-production') },
	{ name: 'servers/networking', path: serverPath('erp-production', 'networking') },
	{ name: 'servers/addresses', path: serverPath('erp-production', 'networking'), target: section('Addresses') },
	{
		name: 'servers/firewall',
		path: serverPath('erp-production', 'networking'),
		target: section('Firewall'),
		setup: (page) => page.locator(section('Firewall')).evaluate((element) => element.scrollIntoView({ block: 'start' })),
	},
	{ name: 'servers/access', path: serverPath('erp-production', 'access') },
	{ name: 'servers/ssh-keys', path: '/settings/ssh-keys' },
	{ name: 'servers/snapshots', path: '/servers/snapshots' },
	{
		name: 'servers/take-snapshot',
		path: serverPath('erp-production', 'snapshots'),
		target: '[role=dialog]',
		async setup(page) {
			await page.getByRole('button', { name: 'Take snapshot' }).first().click()
			await page.getByRole('dialog').waitFor()
		},
	},
	{
		name: 'servers/actions',
		path: serverPath('erp-production'),
		async setup(page) {
			await page.getByRole('button', { name: 'Actions' }).click()
			await page.getByRole('menu').waitFor()
		},
	},
	{ name: 'servers/settings', path: serverPath('erp-production', 'settings') },
	{
		name: 'servers/terminate',
		path: serverPath('erp-staging', 'settings'),
		target: '[role=dialog]',
		async setup(page) {
			await page.getByRole('button', { name: 'Terminate' }).click()
			await page.getByRole('dialog').waitFor()
		},
	},
	{
		name: 'servers/create',
		path: '/servers/new',
		setup: answerPlansFromCatalog,
		async steps(studio, page) {
			await studio.type(page.getByPlaceholder('e.g. Acme Production'), 'pos-mumbai')
			await studio.click(page.getByText('Frappe', { exact: true }).first())
			await studio.click(page.getByText('Add a key for SSH access'))
			await studio.click(page.getByRole('option', { name: "Zara's MacBook" }))
			await page.keyboard.press('Escape')
			await studio.click(page.getByText('Enable firewall', { exact: true }))

			const plan = page.getByRole('button', { name: /2 vCPU · 4 GB RAM/ }).first()
			await plan.scrollIntoViewIfNeeded()
			await studio.wait(400)
			await studio.click(plan)
			await studio.moveTo(page.getByRole('button', { name: 'Create server' }))
			await studio.zoomOut()
		},
	},
]
