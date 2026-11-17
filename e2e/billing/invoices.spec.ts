import { expect } from '@playwright/test'
import { test } from '../fixtures'

test('Lists the seeded invoices', async ({ page, users }) => {
	await users.signIn({ scenario: 'with_invoices', currency: 'USD' })

	await page.goto('/dashboard/billing/invoices')

	await expect(page.getByRole('row').filter({ hasText: 'Paid' })).toHaveCount(1)
	await expect(page.getByRole('row').filter({ hasText: 'Outstanding' })).toHaveCount(1)
})

test('Opens an invoice receipt', async ({ page, users }) => {
	await users.signIn({ scenario: 'with_invoices', currency: 'USD' })

	await page.goto('/dashboard/billing/invoices')
	await page.getByRole('row').filter({ hasText: 'Paid' }).click()

	await expect(page.getByText('Subtotal')).toBeVisible()
	await expect(page.getByText('Total', { exact: true })).toBeVisible()
})

test('A new team has no invoices', async ({ page, users }) => {
	await users.signIn({ scenario: 'ready' })

	await page.goto('/dashboard/billing/invoices')

	await expect(page.getByText('No invoices yet')).toBeVisible()
})

test('A failed invoice load offers a retry that works', async ({ page, playwright, baseURL, users, teams }) => {
	const owner = await users.signIn({ scenario: 'with_invoices', currency: 'USD' })
	// A Developer holds no billing view, so the server refuses the invoice list.
	const member = await teams.addMember({ owner, role: 'Developer' })
	await users.login(member)
	await page.addInitScript((team) => localStorage.setItem('central.console.activeTeam', team), owner.team)

	await page.goto('/dashboard/billing/invoices')

	await expect(page.getByText("Couldn't load your invoices")).toBeVisible()
	await expect(page.getByText('No invoices yet')).toBeHidden()

	// The owner grants the Billing role from their own session, as Manage access does.
	const ownerApi = await playwright.request.newContext({ baseURL })
	const login = await ownerApi.post('/api/method/login', { form: { usr: owner.email, pwd: owner.password } })
	expect(login.ok(), `login failed: ${login.status()}`).toBeTruthy()
	const grant = await ownerApi.post('/api/method/central.api.teams.set_team_member_roles', {
		form: { team: owner.team, user: member.email, roles: JSON.stringify([{ role: 'Billing' }]) },
	})
	expect(grant.ok(), `set_team_member_roles failed: ${grant.status()} ${await grant.text()}`).toBeTruthy()
	await ownerApi.dispose()

	await page.getByRole('button', { name: 'Retry' }).click()

	await expect(page.getByRole('row').filter({ hasText: 'Paid' })).toHaveCount(1)
	await expect(page.getByText("Couldn't load your invoices")).toBeHidden()
})
