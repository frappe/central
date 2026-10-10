import { expect } from '@playwright/test'
import { test } from '../fixtures'

test('Invite and accept a team member', async ({ page, users }) => {
	const invitee = await users.seed()
	const owner = await users.signIn()

	// send invite dialog
	await page.goto('/dashboard/team/members')
	await page.getByRole('button', { name: 'Invite' }).click()
	await page.getByRole('textbox', { name: 'Email 1' }).fill(invitee.email)
	await page.getByRole('combobox', { name: 'Role 1' }).click()
	await page.getByRole('option', { name: 'Developer' }).click()
	await page.getByRole('button', { name: 'Send 1 invitation' }).click()

	await expect(page.getByRole('row', { name: invitee.email })).toContainText('Invited')

	// accept invite
	await users.login(invitee)
	await page.goto('/dashboard/invitations')
	await page.getByRole('button', { name: 'Accept & join' }).click()

	await expect(page.getByText('No invitations')).toBeVisible()

	// verify invitee as member
	await users.login(owner)
	await page.goto('/dashboard/team/members')

	const member = page.getByRole('row', { name: invitee.email })
	await expect(member).not.toContainText('Invited')
})

test('A batch invite keeps only the refused rows', async ({ page, users }) => {
	const invitee = await users.seed()
	const owner = await users.signIn()

	await page.goto('/dashboard/team/members')
	await page.getByRole('button', { name: 'Invite' }).click()
	await page.getByRole('textbox', { name: 'Email 1' }).fill(invitee.email)
	await page.getByRole('button', { name: 'Add another' }).click()
	// The owner is already a member, so the server refuses this row.
	await page.getByRole('textbox', { name: 'Email 2' }).fill(owner.email)
	await page.getByRole('button', { name: 'Send 2 invitations' }).click()

	const dialog = page.getByRole('dialog')
	await expect(dialog.getByText('This user is already a team member.')).toBeVisible()
	await expect(dialog.getByRole('textbox', { name: 'Email 1' })).toHaveValue(owner.email)
	await expect(dialog.getByRole('textbox', { name: 'Email 2' })).toHaveCount(0)
	await expect(dialog.getByRole('button', { name: 'Send 1 invitation' })).toBeVisible()

	await dialog.getByRole('button', { name: 'Cancel' }).click()
	await expect(page.getByRole('row', { name: invitee.email })).toContainText('Invited')
})
