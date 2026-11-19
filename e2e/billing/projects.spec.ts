import { expect } from '@playwright/test'
import { test } from '../fixtures'

test('A new team has no projects', async ({ page, users }) => {
	await users.signIn({ scenario: 'ready' })

	await page.goto('/dashboard/billing')

	await expect(page.getByText('Group invoice costs by customer or environment.')).toBeVisible()
	await expect(page.getByRole('button', { name: 'View all' })).toHaveCount(0)
})

test('Create a project', async ({ page, users }) => {
	await users.signIn({ scenario: 'ready' })

	await page.goto('/dashboard/billing')
	await page.getByRole('button', { name: 'New project' }).click()
	await page.getByLabel('Title').fill('Acme Staging')
	await page.getByRole('button', { name: 'Create', exact: true }).click()
	await page.getByRole('button', { name: 'View all' }).click()

	await expect(page.getByText('Acme Staging')).toBeVisible()
})
