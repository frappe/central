import { expect } from '@playwright/test'
import { test } from '../fixtures'

test('A new team has no billing history', async ({ page, users }) => {
	await users.signIn({ scenario: 'ready' })

	await page.goto('/dashboard/billing')

	await expect(
		page.getByText('Your spend, payments and tax show up here after your first invoice.'),
	).toBeVisible()
})

test('Summarises spend once invoices exist', async ({ page, users }) => {
	await users.signIn({ scenario: 'with_invoices', currency: 'USD' })

	await page.goto('/dashboard/billing')

	await expect(page.getByText('Monthly average')).toBeVisible()
	await expect(page.getByText('Paid by credits')).toBeVisible()
})
