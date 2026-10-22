import { expect, test } from '../trials'

test('The progress page follows the resize to the last step', async ({ browser, trials }) => {
	// The page is public, so it opens in a context with no session. A seeded site never
	// answers, so the live page stops at Landing; the preview test covers Ready.
	const trial = await trials.start({ trialState: '' })
	const change = await trials.queuePlanChange(trial)
	const page = await (await browser.newContext()).newPage()

	await page.goto(change.url)

	await expect(page.getByRole('heading', { name: 'Upgrading your site' })).toBeVisible()
	await expect(page.locator('#ticket-status')).toHaveText('In flight')
	await expect(page).toHaveTitle('Upgrading (2 of 3)')

	await trials.setActionStatus(change.action, 'Succeeded')

	await expect(page.locator('#ticket-status')).toHaveText('Landing', { timeout: 10_000 })
	await expect(page).toHaveTitle('Upgrading (3 of 3)')
	await expect(page.getByText('Almost there. Waiting for your site to answer.')).toBeVisible()
})

test('A failed resize says so and links back to the site', async ({ browser, trials }) => {
	const trial = await trials.start({ trialState: '' })
	const change = await trials.queuePlanChange(trial, 'Failed')
	const page = await (await browser.newContext()).newPage()

	await page.goto(change.url)

	await expect(page.getByRole('heading', { name: 'The upgrade did not finish' })).toBeVisible()
	await expect(page.getByRole('link', { name: 'Go to your site' })).toHaveAttribute('href', `https://${trial.site}`)
	await expect(page.locator('#ticket')).toBeHidden()
})

test('A changed link is not valid', async ({ browser, trials }) => {
	const trial = await trials.start({ trialState: '' })
	const change = await trials.queuePlanChange(trial)
	const page = await (await browser.newContext()).newPage()

	await page.goto(change.url.replace(/_signature=[0-9a-f]+/, `_signature=${'0'.repeat(128)}`))

	await expect(page.getByRole('heading', { name: 'This link is not valid' })).toBeVisible()
})

test('The preview lands the plane and lets the user stay on the page', async ({ page }) => {
	await page.goto(`${progressOrigin()}/upgrading?preview=1`)

	await page.getByLabel('Ready').check()

	await expect(page.getByRole('heading', { name: 'Your site is ready' })).toBeVisible()
	await expect(page.locator('#ticket-status')).toHaveText('Arrived')
	await expect(page.getByText(/Taking you there in \d seconds?/)).toBeVisible()

	await page.getByRole('button', { name: 'Stay on this page' }).click()
	await expect(page.getByText('You can open your site when you are ready.')).toBeVisible()
})

// Central serves the page; the console under test may run on a dev server in front of it.
function progressOrigin() {
	return process.env.E2E_SITE_URL || 'http://central.localhost:8001'
}
