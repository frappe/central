import { expect, test } from '../billing/fixtures'

test('invite', async ({ page, billing }) => {
	const invitee = await billing.seed()
	const owner = await billing.signIn()

	// send invite dialog
	await page.goto('/dashboard/team/members')
	await page.getByRole('button', { name: 'Invite' }).click()
	await page.getByLabel('Email').fill(invitee.email)
	await page.getByRole('combobox', { name: 'Role' }).click()
	await page.getByRole('option', { name: 'Developer' }).click()
	await page.getByRole('button', { name: 'Send invite' }).click()

	await expect(page.getByRole('row', { name: invitee.email })).toContainText('Invited')

	// accept invite
	await billing.login(invitee)
	await page.goto('/dashboard/invitations')
	await page.getByRole('button', { name: 'Accept & join' }).click()

	await expect(page.getByText('No invitations')).toBeVisible()

	// verify invitee as member
	await billing.login(owner)
	await page.goto('/dashboard/team/members')

	const member = page.getByRole('row', { name: invitee.email })
	await expect(member).not.toContainText('Invited')
})
