import { expect, type Page } from '@playwright/test'
import { test } from '../fixtures'

async function switchTo(page: Page, label: string): Promise<void> {
	await page.getByRole('button', { name: 'Switch team', exact: true }).click()
	const team = page.getByRole('button', { name: label, exact: true })
	if ((await team.getAttribute('aria-pressed')) === 'true') {
		await page.keyboard.press('Escape')
		return
	}
	await team.click()
	await expect(page.getByRole('button', { name: 'Switch team', exact: true })).toContainText(label)
}

test('switching refreshes the team roster and keeps the current section', async ({ page, users, teams }) => {
	const owner = await users.signIn()
	const member = await teams.addMember({ owner })

	const shared = await page.request.post('/api/method/central.api.teams.rename_team', {
		form: { team: owner.team, team_name: 'Shared E2E Team' },
	})
	expect(shared.ok()).toBeTruthy()
	await users.login(member)
	const personal = await page.request.post('/api/method/central.api.teams.rename_team', {
		form: { team: member.team, team_name: 'Personal E2E Team' },
	})
	expect(personal.ok()).toBeTruthy()
	await page.goto('/dashboard/team/members')

	await switchTo(page, 'Personal E2E Team')
	await expect(page.getByRole('main')).toContainText('1 member')
	await expect(page).toHaveURL(/\/dashboard\/team\/members$/)

	await switchTo(page, 'Shared E2E Team')
	await expect(page.getByRole('main')).toContainText('2 members')
	await expect(page).toHaveURL(/\/dashboard\/team\/members$/)
})

test('the right edge of the sidebar Team item opens the page', async ({ page, users }) => {
	await users.signIn()
	await page.goto('/dashboard/servers')
	const team = page.getByRole('link', { name: 'Team', exact: true })
	const bounds = await team.boundingBox()
	expect(bounds).not.toBeNull()
	await page.mouse.click(bounds!.x + bounds!.width - 2, bounds!.y + bounds!.height / 2)
	await expect(page).toHaveURL(/\/dashboard\/team\/members$/)
})
