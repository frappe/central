import { expect, test } from '../billing/fixtures'

test('Rename the team', async ({ page, billing }) => {
	await billing.signIn()

	await page.goto('/dashboard/team/members')
	await page.getByRole('button', { name: 'Edit team' }).click()
	await page.getByLabel('Team name').fill('Renamed Team')
	await page.getByRole('button', { name: 'Save' }).click()
	await page.keyboard.press('Escape')

	await expect(page.getByRole('main').getByText('Renamed Team', { exact: true })).toBeVisible()
})
