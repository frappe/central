import { test, expect } from './fixtures'

// Read path: a team with one settled and one outstanding invoice sees both on the
// Invoices screen, each with the right amount and status badge, and can open one
// to read its line items + tax block. No mocks — the rows come from real Invoice
// docs the seed inserted for this team.
// TODO: legacy dashboard removed; console's BillingInvoicesPage has different
// markup (split-view, no `ul.divide-y > li` rows). Rewrite against console's
// actual DOM and un-skip.
test.describe.skip('Invoices', () => {
  test('lists the seeded paid and open invoices', async ({ page, billing }) => {
    await billing.signIn({ scenario: 'with_invoices', currency: 'USD' })

    await page.goto('/legacy-dashboard/billing/invoices')

    const rows = page.locator('ul.divide-y > li')
    await expect(rows).toHaveCount(2)
    await expect(rows.filter({ hasText: 'Paid' })).toHaveCount(1)
    await expect(rows.filter({ hasText: 'Open' })).toHaveCount(1)
    // Both invoices total $1,180.00 (1000 + 180 tax) in the seeded scenario.
    await expect(rows.filter({ hasText: '1,180' })).toHaveCount(2)
  })

  test('opens an invoice to show its line items and tax', async ({ page, billing }) => {
    await billing.signIn({ scenario: 'with_invoices', currency: 'USD' })

    await page.goto('/legacy-dashboard/billing/invoices')
    await page.locator('ul.divide-y > li').filter({ hasText: 'Paid' }).click()

    // Detail pane: line-item table + the totals/tax block from the seeded invoice.
    await expect(page.getByText('Line items')).toBeVisible()
    const totals = page.locator('dl').filter({ hasText: 'Total' })
    await expect(totals.getByText('Subtotal')).toBeVisible()
    await expect(totals.getByText('VAT')).toBeVisible() // USD output tax in the seed
    await expect(totals.getByText('1,180').first()).toBeVisible() // total = subtotal + tax
  })
})
