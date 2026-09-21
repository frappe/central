import { expect } from '@playwright/test'
import { test } from '../fixtures'

const openMemberRow = async (page, users, teams) => {
	const owner = await users.signIn()
	const member = await teams.addMember({ owner })

	await page.goto('/dashboard/team/members')

	return page.getByRole('row', { name: member.email })
}

test('Change member role', async ({ page, users, teams }) => {
	const row = await openMemberRow(page, users, teams)

	await row.getByRole('button', { name: 'Member actions' }).click()
	await page.getByRole('menuitem', { name: 'Manage access' }).click()

	const dialog = page.getByRole('dialog', { name: 'Manage access' })
	await dialog.getByRole('combobox').first().click()
	await page.getByRole('option', { name: 'Viewer' }).click()
	await dialog.getByRole('button', { name: 'Save' }).click()

	await expect(row).toContainText('Viewer')
})

test('Remove a member', async ({ page, users, teams }) => {
	const row = await openMemberRow(page, users, teams)

	await row.getByRole('button', { name: 'Member actions' }).click()
	await page.getByRole('menuitem', { name: 'Remove from team' }).click()
	await page.getByRole('button', { name: 'Remove', exact: true }).click()

	await expect(row).toBeHidden()
})
