import { expect } from '@playwright/test'
import { test } from '../fixtures'

const switchTo = async (page, role) => {
	await page.getByRole('button', { name: /Frappe Cloud/ }).click()
	await page.getByRole('menuitem', { name: 'Switch team' }).click()

	const dialog = page.getByRole('dialog')
	await expect(dialog.getByRole('row').filter({ hasText: "Cust's Team" })).toHaveCount(2)

	await dialog
		.getByRole('row')
		.filter({ hasText: role })
		.getByRole('button', { name: 'Team actions' })
		.click()
	await page.getByRole('menuitem', { name: 'Switch team' }).click()
}

test('Switch between teams', async ({ page, users, teams }) => {
	const owner = await users.signIn()
	const member = await teams.addMember({ owner })

	await users.login(member)
	await page.goto('/dashboard/team/members')

	await switchTo(page, 'Owner')
	await expect(page.getByRole('main')).toContainText('1 member')

	await switchTo(page, 'Developer')
	await expect(page.getByRole('main')).toContainText('2 members')
})
