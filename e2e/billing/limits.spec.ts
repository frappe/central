import { expect } from '@playwright/test'
import { test } from '../fixtures'

test('Shows this cycle and the tiers', async ({ page, users, teams }) => {
	const { team } = await users.signIn({ scenario: 'ready' })
	await teams.setTrustTier({ team })

	await page.goto('/dashboard/billing')
	await page.getByRole('button', { name: 'Tiers', exact: true }).click()

	await expect(page.getByText('Limit tiers')).toBeVisible()
	await expect(page.getByText('To qualify')).toBeVisible()
})
