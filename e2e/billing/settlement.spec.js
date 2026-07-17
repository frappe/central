import { test, expect } from './fixtures'

// Invoice settlement through the real credits-then-card waterfall (no mocks). Each
// test arranges real backend state (wallet credits, a real Stripe test card, a
// Draft invoice), runs the real `open_and_collect` waterfall, and asserts the
// outcome on the rendered dashboard. Card charges hit a genuine off-session
// PaymentIntent; the Open → Paid flip is delivered by the real apply_webhook with
// the real captured transaction id (the local bench can't receive live webhooks).

const open = (page) => page.locator('ul.divide-y > li')

// TODO: legacy dashboard removed; these flows (billing/invoices, billing/credits)
// aren't ported to console yet. Un-skip once console has them.
test.describe.skip('Invoice settlement', () => {
  test('settles fully from wallet credits — no card charged', async ({ page, billing }) => {
    const { team } = await billing.signIn({ scenario: 'ready', currency: 'USD' })
    await billing.addCredits({ team, amount: 2000 })
    const { invoice } = await billing.makeInvoice({ team, total: 1180 })

    // Credits ($2,000) cover the $1,180 bill in full → Paid with no gateway charge.
    const res = await billing.settle({ team, invoice, collect: 1 })
    expect(res.status).toBe('Paid')

    await page.goto('/legacy-dashboard/billing/invoices')
    await expect(open(page).filter({ hasText: 'Paid' })).toHaveCount(1)
    await open(page).filter({ hasText: 'Paid' }).click()
    await expect(page.locator('dl').getByText('Credit applied')).toBeVisible()

    // Wallet dropped by the full invoice total ($2,000 − $1,180 = $820).
    await page.goto('/legacy-dashboard/billing/credits')
    await expect(page.getByText('$820.00').first()).toBeVisible()
    await expect(page.getByText(new RegExp(`Credit applied to ${invoice}`))).toBeVisible()
  })

  test('settles partly from credits, charges the remainder to the card', async ({ page, billing }) => {
    const { team } = await billing.signIn({ scenario: 'ready', currency: 'USD' })
    await billing.addCredits({ team, amount: 500 })
    await billing.saveCard({ team })
    const { invoice } = await billing.makeInvoice({ team, total: 1180 })

    // $500 credit applied, the $680 remainder charged to the real test card.
    const res = await billing.settle({ team, invoice, collect: 1 })
    expect(res.credit_applied).toBe(500)
    expect(res.expected_collection).toBe(680)
    expect(res.attempt).toBeTruthy() // a captured off-session PaymentIntent
    await billing.deliverWebhook({ attempt: res.attempt }) // flips Open → Paid

    await page.goto('/legacy-dashboard/billing/invoices')
    await expect(open(page).filter({ hasText: 'Paid' })).toHaveCount(1)
    await open(page).filter({ hasText: 'Paid' }).click()
    const totals = page.locator('dl')
    await expect(totals.getByText('Credit applied')).toBeVisible()
    await expect(totals.getByText('$500.00')).toBeVisible() // credit leg
    await expect(totals.getByText('Paid', { exact: true })).toBeVisible()

    // Wallet fully drained by the $500 it contributed.
    await page.goto('/legacy-dashboard/billing/credits')
    await expect(page.getByText('$0.00').first()).toBeVisible()
  })

  test('charges a saved card from the invoice "Pay" button', async ({ page, billing }) => {
    const { team } = await billing.signIn({ scenario: 'ready', currency: 'USD' })
    await billing.saveCard({ team })
    // linkCard attaches a subscription pointing at the card, so the Pay button resolves it.
    const { invoice } = await billing.makeInvoice({ team, total: 1180, linkCard: 1 })

    // Open the invoice without charging (no credits) so the UI button drives the charge.
    const res = await billing.settle({ team, invoice, collect: 0 })
    expect(res.status).toBe('Open')

    await page.goto('/legacy-dashboard/billing/invoices')
    await open(page).filter({ hasText: 'Open' }).click()

    // The detail pane offers "Pay $1,180.00"; clicking it runs the real off-session
    // charge. Capture the attempt from the response to deliver its webhook.
    const payResp = page.waitForResponse((r) => r.url().includes('pay_invoice'))
    await page.getByRole('button', { name: /^Pay \$1,180/ }).click()
    const charge = (await (await payResp).json()).data
    expect(charge.charged).toBe(true)
    expect(charge.attempt).toBeTruthy()

    // The webhook settles it; the invoice flips to Paid in the UI.
    await billing.deliverWebhook({ attempt: charge.attempt })
    await page.goto('/legacy-dashboard/billing/invoices')
    await expect(open(page).filter({ hasText: 'Paid' })).toHaveCount(1)
    await expect(open(page).filter({ hasText: 'Open' })).toHaveCount(0)
  })
})
