const dialog = '[role="dialog"]'
const server = ({ servers }) => `/servers/${servers['erp-production']}`

async function openSupport(page) {
	await page.getByRole('button', { name: 'Actions' }).click()
	await page.getByRole('menuitem', { name: 'Contact support' }).click()
	await page.getByRole('dialog').waitFor()
}

export default [
	{
		name: 'help/support-search',
		path: server,
		target: dialog,
		async setup(page) {
			await openSupport(page)
			await page.getByPlaceholder('Describe what is going wrong').fill('site is slow after update')
			await page.getByText('Help articles').waitFor()
		},
	},
	{
		name: 'help/support-tickets',
		path: server,
		target: dialog,
		async setup(page) {
			await openSupport(page)
			await page.getByRole('button', { name: /Your tickets/ }).click()
		},
	},
	{
		name: 'help/support-ticket',
		path: server,
		async setup(page) {
			await openSupport(page)
			await page.getByPlaceholder('Describe what is going wrong').fill('site is slow after update')
			await page.getByText('Help articles').waitFor()
		},
		async steps(studio, page) {
			await studio.click(page.getByRole('button', { name: 'Still need help?' }))
			await studio.click(page.getByText('Choose the issue'), { zoom: false })
			await studio.click(page.getByRole('option', { name: 'Slow performance or high load' }), { zoom: false })
			await studio.type(page.getByPlaceholder('What were you doing, what did you expect, and what error did you see?'), '. Pages take 10 seconds to open since this morning.')
			await studio.moveTo(page.getByRole('button', { name: 'Send to support' }))
			await studio.wait(900)
		},
	},
]
