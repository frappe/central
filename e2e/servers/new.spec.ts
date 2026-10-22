import { expect } from '@playwright/test'
import { test } from '../fixtures'

const openForm = async (page, users, teams, scenario) => {
	const { team } = await users.signIn({ scenario })
	await teams.setTrustTier({ team })

	await page.goto('/dashboard/servers/new')
	await page.getByPlaceholder('e.g. Acme Production').fill('Test Server')
	await page.getByRole('button', { name: 'Region Bengaluru, India' }).click()

	return page.locator('label:has(input[type=radio])').first()
}

test('Create stays disabled until a plan is picked', async ({ page, users, teams }) => {
	const plan = await openForm(page, users, teams, 'ready')

	const create = page.getByRole('button', { name: /Create server/ })
	await expect(create).toBeDisabled()

	await plan.click()

	await expect(create).toBeEnabled()
})

test('Creating needs billing details', async ({ page, users, teams }) => {
	const plan = await openForm(page, users, teams, 'profile_pending')

	await plan.click()
	await page.getByRole('button', { name: /Create server/ }).click()

	await expect(page).toHaveURL(/\/dashboard\/billing$/)
	await expect(page.getByText('Add your billing details to continue')).toBeVisible()
})
