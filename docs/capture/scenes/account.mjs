async function openSettingsTab(page, tab) {
	await page.getByRole('button', { name: /Zara Quill/ }).click()
	await page.getByRole('menuitem', { name: 'My profile' }).click()
	const dialog = page.getByRole('dialog')
	await dialog.waitFor()
	if (tab) await dialog.getByText(tab, { exact: true }).first().click()
}

export default [
	{
		name: 'account/profile',
		path: '/servers',
		target: '[role="dialog"]',
		setup: (page) => openSettingsTab(page),
	},
	{
		name: 'account/preferences',
		path: '/servers',
		target: '[role="dialog"]',
		setup: (page) => openSettingsTab(page, 'Preferences'),
	},
	{
		name: 'account/notification-settings',
		path: '/servers',
		target: '[role="dialog"]',
		async setup(page) {
			await openSettingsTab(page, 'Notifications')
			await page.getByRole('button', { name: 'Save preferences' }).waitFor()
		},
	},
	{
		name: 'account/notifications-panel',
		path: '/servers',
		async setup(page) {
			await page.getByText('Notifications', { exact: true }).first().click()
			await page.getByText('All categories').first().waitFor()
		},
	},
	{
		name: 'account/user-menu',
		path: '/servers',
		async setup(page) {
			await page.getByRole('button', { name: /Zara Quill/ }).click()
			await page.getByRole('menuitem', { name: 'My profile' }).waitFor()
		},
	},
]
