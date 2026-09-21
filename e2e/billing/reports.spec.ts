import { expect } from '@playwright/test'
import { test } from '../fixtures'

test('A new team has no billing history', async ({ page, users }) => {
	await users.signIn({ scenario: 'ready' })

	await page.goto('/dashboard/billing/reports')

	await expect(page.getByText('No billing history yet')).toBeVisible()
})

test('Summarises spend once invoices exist', async ({ page, users }) => {
	await users.signIn({ scenario: 'with_invoices', currency: 'USD' })

	await page.goto('/dashboard/billing/reports')

	await expect(page.getByText('Total spend')).toBeVisible()
	await expect(page.getByText('Average month')).toBeVisible()
})
