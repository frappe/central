import { expect } from '@playwright/test'
import { test } from '../fixtures'

const openSettings = async (page, me, tab) => {
	await page.goto('/dashboard/servers')
	await page.getByRole('button', { name: me.email }).click()
	await page.getByRole('menuitem', { name: 'My profile' }).click()

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

test('Change your password', async ({ page, users }) => {
	const me = await users.signIn()

	await openSettings(page, me)
	await page.getByRole('button', { name: 'Change password' }).click()
	await page.getByLabel('Current password').fill(me.password)
	await page.getByLabel('New password').fill('a-longer-password')
	await page.getByRole('button', { name: 'Update password' }).click()

	await expect(page.getByText('Password changed')).toBeVisible()
})

test('Save notification preferences', async ({ page, users }) => {
	const me = await users.signIn()

	await openSettings(page, me, 'Notifications')
	const billingEmails = page.getByLabel('Email notifications for Billing').getByRole('switch')
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

test('Asks before deleting the team', async ({ page, users }) => {
	const me = await users.signIn()

	await openSettings(page, me, 'Team')
	await page.getByRole('button', { name: 'Delete', exact: true }).click()

	await expect(page.getByRole('dialog', { name: 'Delete team' })).toContainText("This can't be undone")
})
