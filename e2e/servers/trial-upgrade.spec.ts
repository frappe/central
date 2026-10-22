import { expect, test } from '../trials'

// The link a site's Change plan button opens. A fresh page, as a new tab from the site gets.
const openChangePlan = (page, audience) => page.goto(`/dashboard/servers?pilot=${audience}&action=resize`)

test('A trial server asks for a payment method, and names the credit and the sleep', async ({ page, trials }) => {
	const trial = await trials.start({ trialState: 'Active' })

	await openChangePlan(page, trial.audience)

	const dialog = page.getByRole('dialog')
	await expect(dialog.getByText('Upgrade your site')).toBeVisible()
	await expect(dialog.getByText('Your free trial ends in 5 days')).toBeVisible()
	await expect(dialog.getByText(/Add a payment method by .+ and get .+ credit/)).toBeVisible()
	await expect(dialog.getByText(/Until you add a payment method, your site sleeps after \d+ minutes?/)).toBeVisible()
	await expect(dialog.getByRole('button', { name: 'Add payment method' })).toBeVisible()
})

test('An ended trial shows the deletion date, with no credit and no sleep note', async ({ page, trials }) => {
	const trial = await trials.start({ trialState: 'Ended' })

	await openChangePlan(page, trial.audience)

	const dialog = page.getByRole('dialog')
	await expect(dialog.getByText('Your free trial has ended')).toBeVisible()
	await expect(dialog.getByText(/This site is stopped. Add a payment method before/)).toBeVisible()
	await expect(dialog.getByText(/and get .+ credit/)).toHaveCount(0)
	await expect(dialog.getByText(/sleeps after/)).toHaveCount(0)
})

test('A payment method during the trial earns the credit and opens the plans', async ({ page, trials }) => {
	const trial = await trials.start({ trialState: 'Active' })

	const { balance } = await trials.addPaymentMethod(trial.team)
	expect(balance).toBeGreaterThan(0)

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
	await expect(dialog.getByText(/Keep it before .+ to start it again on its paid plan/)).toBeVisible()
	await expect(dialog.getByRole('button', { name: 'Keep this site' })).toBeVisible()
	await expect(dialog.getByRole('button', { name: 'Add payment method' })).toHaveCount(0)
})

test('A payment method after the trial ended earns no credit', async ({ trials }) => {
	const trial = await trials.start({ trialState: 'Ended' })

	const { balance } = await trials.addPaymentMethod(trial.team)

	expect(balance).toBe(0)
})

test('A team without a trial resizes directly and gets the credit with its first card', async ({ page, trials }) => {
	const server = await trials.start({ trialState: '' })

	await openChangePlan(page, server.audience)

	const dialog = page.getByRole('dialog')
	await expect(dialog.getByText('Resize server')).toBeVisible()
	await expect(dialog.getByText(/Choose a new CPU and memory size/)).toBeVisible()
	await expect(dialog.getByText(/free trial/)).toHaveCount(0)

	const { balance } = await trials.addPaymentMethod(server.team)
	expect(balance).toBeGreaterThan(0)
})

test('A server with a resize in progress cannot change plan again', async ({ page, trials }) => {
	const server = await trials.start({ trialState: '' })
	await trials.queuePlanChange(server)

	await openChangePlan(page, server.audience)

	await expect(page.getByText("This server can't be resized right now.")).toBeVisible()
	await expect(page.getByRole('dialog')).toHaveCount(0)
})
