import { expect } from '@playwright/test'
import { test } from './fixtures'

test('Shows the billing cards', async ({ page, users }) => {
	await users.signIn({ scenario: 'ready' })

	await page.goto('/dashboard/billing/payments')

	await expect(page.getByRole('heading', { name: 'Methods' })).toBeVisible()
	await expect(page.getByRole('heading', { name: 'Billing details' })).toBeVisible()
})

test('Asks a new team for billing details', async ({ page, users }) => {
	await users.signIn()

	await page.goto('/dashboard/billing')

	await expect(page.getByText('Add your billing details')).toBeVisible()
})

test('Shows the wallet balance', async ({ page, users, billing }) => {
	const { team } = await users.signIn({ scenario: 'ready' })
	await billing.addCredits({ team, amount: 500 })

	await page.goto('/dashboard/billing/payments')

	await expect(page.getByText('Prepaid credits')).toBeVisible()
	await expect(page.getByText('₹500.00 balance')).toBeVisible()
})
