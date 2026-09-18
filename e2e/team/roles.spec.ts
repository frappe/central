import { expect, test } from '../fixtures'

test('Create a role', async ({ page, users }) => {
	await users.signIn()

	await page.goto('/dashboard/team/members')
	await page.getByRole('radio', { name: 'Roles' }).click()
	await page.getByRole('button', { name: 'New role' }).click()
	await page.getByLabel('Role name').fill('Server Watcher')
	await page.getByRole('checkbox', { name: 'View servers, their status, and their metrics' }).check()
	await page.getByRole('button', { name: 'Create role' }).click()

	await expect(page.getByRole('row', { name: 'Server Watcher' })).toBeVisible()
})
