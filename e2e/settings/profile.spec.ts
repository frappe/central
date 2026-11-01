import { expect } from '@playwright/test'
import { test } from '../fixtures'

const openSettings = async (page, me, tab) => {
	await page.goto('/dashboard/servers')
	await page.getByRole('button', { name: me.email }).click()
	await page.getByRole('menuitem', { name: 'Settings' }).click()

	if (tab) await page.getByRole('tab', { name: tab, exact: true }).click()
}

test('Rename yourself', async ({ page, users }) => {
	const me = await users.signIn()

	await openSettings(page, me)
	await page.getByLabel('Full name').fill('Sid Duck')
	await page.getByRole('button', { name: 'Save' }).click()
	await page.keyboard.press('Escape')

	await expect(page.getByRole('button', { name: me.email })).toContainText('Sid Duck')
})

test('Save notification preferences', async ({ page, users }) => {
	const me = await users.signIn()

	await openSettings(page, me, 'Notifications')
	const billingEmails = page.getByRole('switch', { name: 'Email notifications for Billing' })
	await expect(billingEmails).toBeChecked()
	await billingEmails.click()
	await expect(billingEmails).not.toBeChecked()
	await page.getByRole('button', { name: 'Save preferences' }).click()

	await expect(page.getByText('Notification preferences saved')).toBeVisible()
})

test('Switch the theme', async ({ page, users }) => {
	const me = await users.signIn()

	await openSettings(page, me, 'Preferences')
	await page.getByRole('button', { name: 'Light' }).click()

	await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
})

test('Asks the owner to type the team name before archiving', async ({ page, users }) => {
	const me = await users.signIn()

	await openSettings(page, me, 'Team')
	await page.getByRole('button', { name: 'Archive', exact: true }).click()

	const dialog = page.getByRole('dialog', { name: 'Archive team' })
	await expect(dialog.getByText('All servers are terminated')).toBeVisible()
	await expect(dialog.getByRole('button', { name: 'Archive team' })).toBeDisabled()
	await expect(dialog.getByLabel(/^Type .* to confirm$/)).toBeVisible()
})
