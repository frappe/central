const card = (title) => `section:has(> header h2:text-is("${title}"))`

async function scrollTo(page, selector) {
	await page.locator(selector).first().scrollIntoViewIfNeeded()
}

export default [
	{
		name: 'billing/summary',
		path: '/billing',
		target: 'section:has(dl)',
	},
	{
		name: 'billing/spend',
		path: '/billing',
		target: card('Spend'),
		setup: (page) => scrollTo(page, card('Spend')),
	},
	{
		name: 'billing/limits',
		path: '/billing',
		target: 'section:has(h2:text-is("Limits"))',
		setup: (page) => scrollTo(page, 'section:has(h2:text-is("Limits"))'),
	},
	{
		name: 'billing/tiers',
		path: '/billing',
		async setup(page) {
			await page.getByRole('button', { name: 'Tiers', exact: true }).click()
			await page.getByRole('dialog').waitFor()
		},
	},
	{
		name: 'billing/payment-methods',
		path: '/billing/payments',
		target: card('Methods'),
		setup: (page) => scrollTo(page, card('Methods')),
	},
	{
		name: 'billing/add-method',
		path: '/billing/payments',
		target: '[role="dialog"]',
		async setup(page) {
			await scrollTo(page, card('Methods'))
			await page.getByRole('button', { name: /Add another card/ }).click()
			await page.getByRole('dialog').getByText('Card', { exact: true }).waitFor()
		},
	},
	{
		name: 'billing/topup',
		path: '/billing',
		target: '[role="dialog"]',
		async setup(page) {
			await page.getByRole('button', { name: 'Add credit' }).click()
			await page.getByRole('dialog').waitFor()
		},
	},
	{ name: 'billing/invoices', path: '/billing/invoices' },
	{
		name: 'billing/invoice',
		path: '/billing/invoices',
		async setup(page) {
			await page.getByText(/^INV-/).nth(1).click({ force: true })
			await page.getByRole('button', { name: 'Download PDF' }).waitFor()
		},
	},
]
