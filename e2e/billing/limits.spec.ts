import { expect } from '@playwright/test'
import { test } from '../fixtures'

test('Shows this cycle and the tiers', async ({ page, users, teams }) => {
	const { team } = await users.signIn({ scenario: 'ready' })
	await teams.setTrustTier({ team })

	await page.goto('/dashboard/billing/limits')

	await expect(page.getByText('This cycle')).toBeVisible()
	await expect(page.getByText('How tiers work')).toBeVisible()
})
