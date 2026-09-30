import { expect } from '@playwright/test'
import { test } from './fixtures'

const openPanel = async (page) => {
	await page.goto('/dashboard/servers')
	await page.getByRole('button', { name: 'Notifications' }).click()
}

test('Nothing to read yet', async ({ page, users }) => {
	await users.signIn()

	await openPanel(page)

	await expect(page.getByText('Nothing here yet')).toBeVisible()
})

test('A new member shows up as unread', async ({ page, users, teams }) => {
	const owner = await users.signIn()
	await teams.addMember({ owner })

	await openPanel(page)

	await expect(page.getByRole('button', { name: /New team member/ })).toBeVisible()

	await page.getByRole('radio', { name: 'Unread' }).click()

	await expect(page.getByRole('button', { name: /New team member/ })).toBeVisible()
})

test('Reading a notification drops it from Unread', async ({ page, users, teams }) => {
	const owner = await users.signIn()
	await teams.addMember({ owner })

	await openPanel(page)
	await page.getByRole('button', { name: /New team member/ }).click()
	await page.getByRole('radio', { name: 'Unread' }).click()

	await expect(page.getByText("You're all caught up")).toBeVisible()
})

test('Mark all as read empties Unread', async ({ page, users, teams }) => {
	const owner = await users.signIn()
	await teams.addMember({ owner })

	await openPanel(page)
	await page.getByRole('button', { name: 'Mark all as read' }).click()
	await page.getByRole('radio', { name: 'Unread' }).click()

	await expect(page.getByText("You're all caught up")).toBeVisible()
})
