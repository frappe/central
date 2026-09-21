import { expect } from '@playwright/test'
import { test } from '../fixtures'

test('Lists the seeded invoices', async ({ page, users }) => {
	await users.signIn({ scenario: 'with_invoices', currency: 'USD' })

	await page.goto('/dashboard/billing/invoices')

	await expect(page.getByRole('row').filter({ hasText: 'Paid' })).toHaveCount(1)
	await expect(page.getByRole('row').filter({ hasText: 'Open' })).toHaveCount(1)
})

test('Opens an invoice receipt', async ({ page, users }) => {
	await users.signIn({ scenario: 'with_invoices', currency: 'USD' })

	await page.goto('/dashboard/billing/invoices')
	await page.getByRole('row').filter({ hasText: 'Paid' }).click()

	await expect(page.getByText('Subtotal')).toBeVisible()
	await expect(page.getByText('Total', { exact: true })).toBeVisible()
})

test('A new team has no invoices', async ({ page, users }) => {
	await users.signIn({ scenario: 'ready' })

	await page.goto('/dashboard/billing/invoices')

	await expect(page.getByText('No invoices yet')).toBeVisible()
})
