import { expect } from '@playwright/test'
import { test } from '../fixtures'

test.describe('Saved country in an Indian time zone', () => {
	test.use({ timezoneId: 'Asia/Kolkata' })

	test('Shows the saved country and saves nothing on open', async ({ page, users }) => {
		// A complete US profile: the India time-zone guess must not replace it.
		await users.reopenOnboarding(await users.signIn({ scenario: 'ready', currency: 'USD' }))
		const saves: string[] = []
		page.on('request', (request) => {
			if (request.url().includes('save_billing_profile')) saves.push(request.url())
		})

		await page.goto('/dashboard/servers')
		await page.getByRole('dialog', { name: 'Invite your team' }).getByRole('button', { name: 'Skip' }).click()
		const step = page.getByRole('dialog', { name: 'Add a payment method' })
		await expect(step.getByRole('combobox', { name: 'Billing country' })).toHaveValue('United States')
		await page.waitForLoadState('networkidle')

		expect(saves).toHaveLength(0)
	})
})

test.describe('Refused country save', () => {
	// Outside India, so the field does not guess India before the user picks it.
	test.use({ timezoneId: 'America/Chicago' })

	test('A failed country save stops the payment method step', async ({ page, users }) => {
		// A complete US profile with a Texas address: India rejects Texas as a state.
		await users.reopenOnboarding(await users.signIn({ scenario: 'ready', currency: 'USD' }))

		await page.goto('/dashboard/servers')
		await page.getByRole('dialog', { name: 'Invite your team' }).getByRole('button', { name: 'Skip' }).click()
		const step = page.getByRole('dialog', { name: 'Add a payment method' })
		await step.getByRole('combobox', { name: 'Billing country' }).fill('India')
		const picked = page.waitForResponse((response) => response.url().includes('save_billing_profile'))
		await page.getByRole('option', { name: 'India', exact: true }).click()
		expect((await picked).ok()).toBe(false)

		const error = step.getByText("'Texas' is not a recognised Indian state")
		await expect(error).toBeVisible()

		// Continue sends the country again, and stops when the server refuses it.
		const resent = page.waitForResponse((response) => response.url().includes('save_billing_profile'))
		await step.getByRole('button', { name: 'Add payment method' }).click()
		expect((await resent).ok()).toBe(false)

		await expect(error).toBeVisible()
		await expect(page.getByRole('dialog', { name: 'Add payment method' })).toBeHidden()
		await expect(step).toBeVisible()
	})
})
