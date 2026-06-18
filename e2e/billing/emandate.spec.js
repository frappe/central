import { test, expect } from './fixtures'

// INR e-mandate collection (ADR 0005 / #50). An e-mandate team may auto-debit
// silently only up to ₹15,000, and only after an RBI pre-debit notice ≥24h before.
// These tests exercise the real orchestration (emandate.schedule_predebit) and its
// two outcomes, asserting the customer-visible result on the dashboard. No gateway
// debit runs here — that's the separate (token-gated) charge step.
test.describe('INR e-mandate collection', () => {
  test('sends a pre-debit notice for a bill within the ₹15,000 ceiling', async ({ page, billing }) => {
    const { team } = await billing.signIn({ scenario: 'ready', currency: 'INR' })
    await billing.setCollectionMode({ team, mode: 'E-Mandate' })

    const { invoice } = await billing.makeInvoice({ team, total: 5000 })
    await billing.settle({ team, invoice, collect: 0 }) // open it; e-mandate debits later
    const res = await billing.predebit({ invoice })
    expect(res.notified).toBe(true)

    // The customer sees the pre-debit notice in their notification feed.
    await page.goto('/dashboard/settings/notifications')
    await expect(page.getByText('Pre-debit Notice').first()).toBeVisible()
  })

  test('forks a bill over the ceiling to the Action Required choice', async ({ page, billing }) => {
    const { team } = await billing.signIn({ scenario: 'ready', currency: 'INR' })
    await billing.setCollectionMode({ team, mode: 'E-Mandate' })

    const { invoice } = await billing.makeInvoice({ team, total: 20000 }) // over ₹15,000
    await billing.settle({ team, invoice, collect: 0 })
    const res = await billing.predebit({ invoice })
    expect(res.action_required).toBe(true) // can't debit silently → ask the customer

    // The Action Required banner appears on the overview; the customer picks how to pay.
    await page.goto('/dashboard/billing')
    await expect(page.getByText('Action required — choose how to keep paying')).toBeVisible()

    await page.getByRole('button', { name: 'Choose how to pay' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByText('Prepaid wallet').click()
    await dialog.getByRole('button', { name: 'Confirm' }).click()

    // Resolved → the banner clears.
    await expect(page.getByText('Action required — choose how to keep paying')).toHaveCount(0)
  })
})
