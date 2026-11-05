const erp = '/sites/erp.bom.frappe.cloud'
const dialog = '[role="dialog"]'

export default [
	{ app: 'pilot', name: 'pilot/sites', path: '/sites' },
	{ app: 'pilot', name: 'pilot/site-detail', path: erp },
	{
		app: 'pilot',
		name: 'pilot/new-site',
		path: '/sites',
		async setup(page) {
			await page.getByRole('button', { name: 'New site' }).click()
			await page.getByPlaceholder('mysite', { exact: true }).fill('learn')
		},
	},
	{ app: 'pilot', name: 'pilot/storage', path: '/storage' },
	{ app: 'pilot', name: 'pilot/marketplace', path: '/marketplace' },
	{
		app: 'pilot',
		name: 'pilot/install-app',
		path: erp,
		async setup(page) {
			await page.getByRole('button', { name: 'Install app' }).click()
			await page.waitForLoadState('networkidle')
			// Document order puts the card last among the boxes that hold both its title and its button.
			const card = page
				.locator('div')
				.filter({ has: page.getByText('HR & Payroll', { exact: true }) })
				.filter({ has: page.getByRole('button', { name: 'Install' }) })
				.last()
			await card.getByRole('button', { name: 'Install' }).click()
		},
	},
	{ app: 'pilot', name: 'pilot/backups', path: `${erp}/backups` },
	{
		app: 'pilot',
		name: 'pilot/backup-schedule',
		path: `${erp}/backups`,
		setup: (page) => page.getByRole('button', { name: 'Configure' }).click(),
		target: dialog,
	},
	{ app: 'pilot', name: 'pilot/domains', path: `${erp}/settings` },
	{
		app: 'pilot',
		name: 'pilot/add-domain-records',
		path: `${erp}/settings`,
		async setup(page) {
			await page.getByText('Use your own domain').first().click()
			await page.locator(`${dialog} input`).first().fill('erp.contrail.example')
			await page.getByRole('button', { name: 'Continue' }).click()
		},
		target: dialog,
	},
	{ app: 'pilot', name: 'pilot/tasks', path: '/insights/tasks' },
	{
		app: 'pilot',
		name: 'pilot/task-detail',
		path: '/insights/tasks',
		// The step output shows host paths, so the steps stay collapsed.
		setup: (page) => page.getByText('Backup Site', { exact: true }).last().click(),
	},
	{ app: 'pilot', name: 'pilot/logs', path: '/insights/logs' },
	{
		app: 'pilot',
		name: 'pilot/db-analyzer',
		path: '/database/analyzer',
		setup: (page) => page.getByText('Database Processes').click(),
	},
	{
		app: 'pilot',
		name: 'pilot/sql-playground',
		path: '/database/sql-playground?site=erp.bom.frappe.cloud',
		async setup(page) {
			await page.locator('.cm-content').click()
			await page.keyboard.press('Meta+A')
			await page.keyboard.type("SELECT name, module, issingle FROM tabDocType WHERE module = 'Selling' LIMIT 8;")
			await page.getByRole('button', { name: 'Execute' }).click()
		},
	},
	{
		app: 'pilot',
		name: 'pilot/code-editor',
		path: '/editor/erpnext',
		async setup(page) {
			await page.getByText('erpnext', { exact: true }).first().click()
			await page.getByText('hooks.py', { exact: true }).first().click()
		},
	},
	{ app: 'pilot', name: 'pilot/settings-general', path: '/settings' },
	{ app: 'pilot', name: 'pilot/ssh-keys', path: '/settings/security/ssh-keys' },
]
