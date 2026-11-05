import { expect } from '@playwright/test'
import { test } from '../fixtures'

test('Creating needs a payment method', async ({ page, users }) => {
	await users.signIn({ scenario: 'profile_pending' })

	await page.goto('/dashboard/servers/new')

	await expect(page.getByText('Add a payment method to create servers')).toBeVisible()
	await expect(page.getByRole('button', { name: 'Add payment method' })).toBeVisible()
})
