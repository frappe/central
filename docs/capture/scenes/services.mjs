const dialog = '[role="dialog"]'
const media = '/object-storage/bucket-media'
const tab = (page, name) => page.getByText(name, { exact: true }).first().click()

export default [
	{ name: 'services/object-storage', path: '/object-storage' },
	{
		name: 'services/create-bucket',
		path: '/object-storage',
		target: dialog,
		async setup(page) {
			await page.getByRole('button', { name: 'Create bucket' }).first().click()
			await page.getByPlaceholder('media', { exact: true }).fill('media')
		},
	},
	{ name: 'services/bucket-files', path: media },
	{ name: 'services/bucket-settings', path: `${media}?tab=settings` },
	{ name: 'services/llm', path: '/llm' },
	{ name: 'services/llm-keys', path: '/llm', setup: (page) => tab(page, 'API keys') },
	{ name: 'services/llm-models', path: '/llm', setup: (page) => tab(page, 'Models') },
	{
		name: 'services/llm-how-to-call',
		path: '/llm',
		target: dialog,
		setup: (page) => page.getByRole('button', { name: 'How to call' }).click(),
	},
	{
		name: 'services/llm-create-key',
		path: '/llm',
		async steps(studio, page) {
			await studio.click(page.getByRole('button', { name: 'Create key' }).first())
			await studio.type(page.getByPlaceholder('e.g. n8n prod'), 'storefront chatbot')
			await studio.type(page.getByPlaceholder('e.g. 10'), '25')
			await studio.moveTo(page.getByRole('button', { name: 'Create', exact: true }))
			await studio.zoomOut()
		},
	},
]
