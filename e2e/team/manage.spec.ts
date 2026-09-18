import { expect, test } from '../billing/fixtures'

const api = (method) => `/api/method/central.api.teams.${method}`

const addMember = async (page, billing) => {
	const member = await billing.seed()
	const owner = await billing.signIn()

	const invite = await page.request.post(api('invite_team_member'), {
		form: { team: owner.team, email: member.email, role: 'Developer' },
	})
	const invitation = (await invite.json()).message

	await billing.login(member)
	await page.request.post(api('accept_invitation'), { form: { invitation } })

	await billing.login(owner)
	await page.goto('/dashboard/team/members')

	return page.getByRole('row', { name: member.email })
}

test('Change member role', async ({ page, billing }) => {
	const row = await addMember(page, billing)

	await row.getByRole('button', { name: 'Member actions' }).click()
	await page.getByRole('menuitem', { name: 'Manage access' }).click()

	const dialog = page.getByRole('dialog', { name: 'Manage access' })
	await dialog.getByRole('combobox').first().click()
	await page.getByRole('option', { name: 'Viewer' }).click()
	await dialog.getByRole('button', { name: 'Save' }).click()

	await expect(row).toContainText('Viewer')
})

test('Remove a member', async ({ page, billing }) => {
	const row = await addMember(page, billing)

	await row.getByRole('button', { name: 'Member actions' }).click()
	await page.getByRole('menuitem', { name: 'Remove from team' }).click()
	await page.getByRole('button', { name: 'Remove', exact: true }).click()

	await expect(row).toBeHidden()
})
