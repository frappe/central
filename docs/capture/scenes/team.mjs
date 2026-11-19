const memberRow = (page, name) => page.getByRole('row').filter({ hasText: name })

async function openTeamSettings(page) {
	await page.getByRole('button', { name: 'Edit team' }).click()
	await page.getByRole('dialog').waitFor()
}

export default [
	{ name: 'team/members', path: '/team/members', target: 'main' },
	{
		name: 'team/invite',
		path: '/team/members',
		async steps(studio, page) {
			await studio.click(page.getByRole('button', { name: 'Invite' }))
			await studio.type(page.getByPlaceholder('teammate@company.com'), 'ziggy.ops@contrail.example')
			await studio.click(page.getByRole('button', { name: 'Add another' }))
			await studio.type(page.getByPlaceholder('teammate@company.com').nth(1), 'mo.finch@contrail.example')
			await studio.moveTo(page.getByRole('button', { name: /Send 2 invitations/ }))
			await studio.zoomOut()
		},
	},
	{
		name: 'team/member-actions',
		path: '/team/members',
		target: 'main',
		async setup(page) {
			await memberRow(page, 'Kofi Brightwater').getByRole('button', { name: 'Member actions' }).click()
			await page.getByRole('menu').waitFor()
		},
	},
	{
		name: 'team/manage-access',
		path: '/team/members',
		target: '[role="dialog"]',
		async setup(page) {
			await memberRow(page, 'Juniper Hale').getByRole('button', { name: 'Member actions' }).click()
			await page.getByRole('menuitem', { name: 'Manage access' }).click()
			await page.getByRole('dialog').waitFor()
		},
	},
	{
		name: 'team/role-capabilities',
		path: '/team/members',
		async setup(page) {
			await page.locator('main').getByText('Roles', { exact: true }).click()
			await page.getByRole('button', { name: 'Open Developer' }).click({ position: { x: 40, y: 10 } })
			await page.locator('#team-page-aside').getByText('Developer').first().waitFor()
		},
	},
	{
		name: 'team/new-role',
		path: '/team/members',
		target: '[role="dialog"]',
		async setup(page) {
			await page.locator('main').getByText('Roles', { exact: true }).click()
			await page.getByRole('button', { name: 'New role' }).click()
			await page.getByRole('dialog').waitFor()
		},
	},
	{
		name: 'team/settings',
		path: '/team/members',
		target: '[role="dialog"]',
		setup: openTeamSettings,
	},
	{
		name: 'team/archive',
		path: '/team/members',
		target: '[role="dialog"]:has(ul[aria-label="Before you archive"])',
		async setup(page) {
			await openTeamSettings(page)
			await page.getByRole('button', { name: 'Archive', exact: true }).click()
			await page.getByRole('list', { name: 'Before you archive' }).waitFor()
		},
	},
	{
		name: 'team/create',
		path: '/team/members',
		target: '[role="dialog"]',
		async setup(page) {
			await page.getByRole('button', { name: 'Switch team' }).click()
			await page.getByRole('button', { name: 'Create team' }).click()
			await page.getByRole('dialog').waitFor()
		},
	},
]
