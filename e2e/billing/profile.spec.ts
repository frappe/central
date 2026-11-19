import { expect } from '@playwright/test'
import { test } from '../fixtures'

test('A new team has no billing details', async ({ page, users }) => {
	await users.signIn()

	await page.goto('/dashboard/billing/payments')

	await expect(page.getByText('Add your billing details')).toBeVisible()
	await expect(page.getByRole('button', { name: 'Add billing details' })).toBeVisible()
})

test('Edit the billing details', async ({ page, users }) => {
	await users.signIn({ scenario: 'ready' })

	await page.goto('/dashboard/billing/payments')
	await page.getByRole('button', { name: 'Edit', exact: true }).click()
	await page.getByLabel('Billing email').fill('accounts@example.com')
	await page.getByRole('button', { name: 'Save' }).click()

	await expect(page.getByText('accounts@example.com')).toBeVisible()
})
