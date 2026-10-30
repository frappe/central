import { expect, test } from '../trials'

// The link a site's Change plan button opens. A fresh page, as a new tab from the site gets.
const openChangePlan = (page, audience) => page.goto(`/dashboard/servers?pilot=${audience}&action=resize`)

test('A trial server asks for a payment method', async ({ page, trials }) => {
	const trial = await trials.start({ trialState: 'Active' })

	await openChangePlan(page, trial.audience)

	const dialog = page.getByRole('dialog')
	await expect(dialog.getByText('Upgrade from free trial')).toBeVisible()
	await expect(dialog.getByText('Your free trial ends in 5 days')).toBeVisible()
	await expect(dialog.getByText(/Add a payment method to keep this site on the .+ plan\. You can choose a bigger plan next\./)).toBeVisible()
	await expect(dialog.getByText(/Billing starts today at .+ a month/)).toBeVisible()
	await expect(dialog.getByRole('button', { name: 'Add payment method' })).toBeVisible()
})

test('An ended trial shows the deletion date', async ({ page, trials }) => {
	const trial = await trials.start({ trialState: 'Ended' })

	await openChangePlan(page, trial.audience)

	const dialog = page.getByRole('dialog')
	await expect(dialog.getByText('Your free trial has ended')).toBeVisible()
	await expect(dialog.getByText(/This site is stopped. Add a payment method before/)).toBeVisible()
})

test('A payment method during the trial opens the plans', async ({ page, trials }) => {
	const trial = await trials.start({ trialState: 'Active' })
	await trials.addPaymentMethod(trial.team)

	await openChangePlan(page, trial.audience)

	const dialog = page.getByRole('dialog')
	await expect(dialog.getByText('Resize server')).toBeVisible()
	await expect(dialog.getByText(/Choose a new CPU and memory size/)).toBeVisible()

	await dialog.getByRole('button', { name: /vCPU/ }).last().click()
	await expect(dialog.getByText(/goes offline for a few minutes/)).toBeVisible()
	await expect(dialog.getByRole('button', { name: 'Resize' })).toBeEnabled()
})

test('A card leaves an ended trial stopped and offers to keep it', async ({ page, trials }) => {
	const trial = await trials.start({ trialState: 'Ended', status: 'Stopped' })
	await trials.addPaymentMethod(trial.team)

	await openChangePlan(page, trial.audience)

	const dialog = page.getByRole('dialog')
	await expect(dialog.getByText('Your free trial has ended')).toBeVisible()
	await expect(dialog.getByText(/Keep it before .+ to start it again on the .+ plan/)).toBeVisible()
	await expect(dialog.getByRole('button', { name: 'Keep this site' })).toBeVisible()
	await expect(dialog.getByRole('button', { name: 'Add payment method' })).toHaveCount(0)
})

test('A team without a trial resizes directly', async ({ page, trials }) => {
	const server = await trials.start({ trialState: '' })

	await openChangePlan(page, server.audience)

	const dialog = page.getByRole('dialog')
	await expect(dialog.getByText('Resize server')).toBeVisible()
	await expect(dialog.getByText(/Choose a new CPU and memory size/)).toBeVisible()
	await expect(dialog.getByText(/free trial/)).toHaveCount(0)
})

test('A server with a resize in progress cannot change plan again', async ({ page, trials }) => {
	const server = await trials.start({ trialState: '' })
	await trials.queuePlanChange(server)

	await openChangePlan(page, server.audience)

	await expect(page.getByText("This server can't be resized right now.")).toBeVisible()
	await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('Billing points an open trial to its Upgrade dialog', async ({ page, trials }) => {
	await trials.start({ trialState: 'Active' })

	await page.goto('/dashboard/billing')

	await expect(page.getByText('Your account is on a free trial')).toBeVisible()
	await expect(page.getByText(/Adding a payment method ends the free trial today/)).toBeVisible()
	await page.getByRole('button', { name: 'Upgrade site' }).click()

	await expect(page.getByRole('dialog').getByText('Upgrade from free trial')).toBeVisible()
})
