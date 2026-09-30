import { expect } from '@playwright/test'
import { test } from '../fixtures'

test('A new team has no projects', async ({ page, users }) => {
	await users.signIn({ scenario: 'ready' })

	await page.goto('/dashboard/billing')

	await expect(page.getByText('No projects yet')).toBeVisible()
})

test('Create a project', async ({ page, users }) => {
	await users.signIn({ scenario: 'ready' })

	await page.goto('/dashboard/billing')
	await page.getByRole('button', { name: 'Create project' }).first().click()
	await page.getByLabel('Title').fill('Acme Staging')
	await page.getByRole('button', { name: 'Create', exact: true }).click()

	await expect(page.getByText('Acme Staging')).toBeVisible()
})
