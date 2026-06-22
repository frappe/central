import { test, expect } from './fixtures'

// First-run setup: a brand-new team (no billing profile) lands on the onboarding
// wizard and completes the required Billing Profile step against the real
// save_billing_profile endpoint — currency, legal name and a full address. Saving
// flips the step to complete, which is what un-gates every money-moving action.
test.describe('Onboarding', () => {
  test('completes the billing profile step', async ({ page, billing }) => {
    await billing.signIn({ scenario: 'profile_pending' })

    await page.goto('/legacy-dashboard/onboarding')
    await expect(page.getByRole('heading', { name: 'Set up billing for your team' })).toBeVisible()
    await expect(page.getByText('0 of 2 done')).toBeVisible()

    // Currency is a frappe-ui (reka-ui) select combobox, not a native <select>:
    // open it and click the option.
    await page.getByRole('combobox', { name: 'Currency *' }).click()
    await page.getByRole('option', { name: 'USD' }).click()

    await page.getByLabel('Legal name *').fill('E2E Test Co')
    await page.getByLabel('Billing email').fill('billing@e2e.example')
    await page.getByLabel('Address line 1 *').fill('1 Market Street')
    await page.getByLabel('City *').fill('San Francisco')

    // Country is a frappe-ui autocomplete (a trigger button + searchable popover):
    // open it, type to filter, pick the option.
    await page.getByRole('button', { name: 'Select country' }).click()
    await page.keyboard.type('United States')
    await page.getByRole('option', { name: 'United States', exact: true }).click()

    // Non-India → State is a plain text field; PIN is required.
    await page.getByLabel('State *').fill('California')
    await page.getByLabel('PIN code *').fill('94105')

    await page.getByRole('button', { name: 'Save & continue' }).click()

    // Step completes → progress advances and the dashboard becomes reachable.
    await expect(page.getByText('Billing profile saved.', { exact: true })).toBeVisible()
    await expect(page.getByText('1 of 2 done')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Go to dashboard' })).toBeEnabled()
  })
})
