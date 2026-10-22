import { expect } from '@playwright/test'
import { test } from '../fixtures'

test('A new team has no servers', async ({ page, users }) => {
	await users.signIn()

	await page.goto('/dashboard/servers')
	await page.getByRole('button', { name: /All servers/ }).click()

	await expect(page.getByText('No servers yet')).toBeVisible()
})

test('Opens the new server form', async ({ page, users }) => {
	await users.signIn()

	await page.goto('/dashboard/servers')
	await page.getByRole('button', { name: 'New server', exact: true }).click()

	await expect(page).toHaveURL(/\/dashboard\/servers\/new$/)
	await expect(page.getByPlaceholder('e.g. Acme Production')).toBeVisible()
})
