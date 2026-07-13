import { test, expect } from './fixtures'

// Invoice GENERATION through the real agentless pipeline (ADR 0006). Unlike the
// other specs, this fabricates nothing: provisioning writes a price-lock at the
// catalog rate (Central, no agent), and generate_draft_invoice computes the line
// items from that lock over the period. We then open the draft and assert the
// generated figure on the dashboard — proving an invoice can be produced from
// recorded runtime, not just hand-built.
// TODO: legacy dashboard removed; console's BillingInvoicesPage has different
// markup. Rewrite against console's actual DOM and un-skip.
test.describe.skip('Invoice generation', () => {
  test('provisions a price-lock and generates the invoice from it', async ({ page, billing }) => {
    const { team } = await billing.signIn({ scenario: 'ready', currency: 'INR' })

    // Real pipeline: provision (writes the lock) → generate_draft_invoice.
    const gen = await billing.generateInvoice({ team, monthlyRate: 3000 })
    expect(gen.subtotal).toBe(3000) // a full June on the ₹3,000 locked plan, computed from the lock
    await billing.settle({ team, invoice: gen.invoice, collect: 0 }) // Draft → Open (no charge)

    await page.goto('/legacy-dashboard/billing/invoices')
    const rows = page.locator('ul.divide-y > li')
    await rows.filter({ hasText: '3,000' }).click()

    // The detail renders the generated line item + total — not a fabricated number.
    await expect(page.getByText('Line items')).toBeVisible()
    await expect(page.locator('dl').filter({ hasText: 'Total' }).getByText('3,000').first()).toBeVisible()
  })
})
