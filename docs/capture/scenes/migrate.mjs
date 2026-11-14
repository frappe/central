const settings = '/sites/erp.bom.frappe.cloud/settings'
const CLASSIC_SITE = 'erp.contrail.example'
const INTEGRATION = /\/api\/v1\/sites\/[^/]+\/integrations\/frappe-cloud(\/backups)?$/
const GIB = 1024 ** 3

const hoursAgo = (hours) => new Date(Date.now() - hours * 3_600_000).toISOString()
const BACKUPS = [
	{ name: 'backup-3', created_at: hoursAgo(5), size_bytes: 3.42 * GIB },
	{ name: 'backup-2', created_at: hoursAgo(29), size_bytes: 3.4 * GIB },
	{ name: 'backup-1', created_at: hoursAgo(53), size_bytes: 3.37 * GIB },
]

/**
 * Stands in for Frappe Cloud Classic. The request starts at `status`, and a pending
 * request is approved after `pollsUntilApproved` status checks.
 */
async function answerAsClassic(page, { status = null, pollsUntilApproved = Infinity } = {}) {
	let polls = 0
	const connection = () => ({ status, remote_site: CLASSIC_SITE, approval_url: 'https://cloud.frappe.io/dashboard/sites', code: 'K7QM2XPA' })

	await page.route(
		(url) => INTEGRATION.test(url.pathname),
		(route) => {
			const method = route.request().method()
			if (route.request().url().includes('/backups')) return route.fulfill({ json: { running_backup: null, backups: BACKUPS } })
			if (method === 'DELETE') status = null
			if (method === 'POST') status = 'Pending'
			if (method === 'GET' && status === 'Pending' && ++polls > pollsUntilApproved) status = 'Approved'
			if (!status) return route.fulfill({ status: 422, json: { error: { code: 'frappe_cloud_error', message: 'Connect to Frappe Cloud first.', details: {} } } })
			return route.fulfill({ json: method === 'DELETE' ? {} : connection() })
		},
	)
}

async function openRestore(page) {
	await page.getByRole('button', { name: 'Restore', exact: true }).click()
	await page.getByRole('dialog').waitFor()
	await page.getByRole('dialog').getByText('Frappe Cloud v1').click()
}

export default [
	{
		app: 'pilot',
		name: 'migrate/pass-code',
		path: settings,
		target: '[role="dialog"]',
		async setup(page) {
			await answerAsClassic(page, { status: 'Pending' })
			await openRestore(page)
			await page.getByText('Waiting for approval').waitFor()
		},
	},
	{
		app: 'pilot',
		name: 'migrate/backups',
		path: settings,
		target: '[role="dialog"]',
		async setup(page) {
			await answerAsClassic(page, { status: 'Approved' })
			await openRestore(page)
			await page.getByText('Take new backup').waitFor()
		},
	},
	{
		app: 'pilot',
		name: 'migrate/connect',
		path: settings,
		setup: (page) => answerAsClassic(page, { pollsUntilApproved: 1 }),
		async steps(studio, page) {
			const dialog = page.getByRole('dialog')
			const restore = page.getByRole('button', { name: 'Restore', exact: true })
			await restore.scrollIntoViewIfNeeded()
			await studio.wait(400)
			await studio.click(restore)
			await studio.click(dialog.getByText('Frappe Cloud v1'))
			await studio.type(dialog.getByPlaceholder('erp.example.com'), CLASSIC_SITE)
			await studio.click(dialog.getByRole('button', { name: 'Connect' }))
			await studio.zoomOut()
			await dialog.getByText('Take new backup').waitFor()
			await studio.wait(1200)
			await studio.moveTo(dialog.getByRole('button', { name: 'Restore', exact: true }))
			await studio.wait(900)
		},
	},
]
