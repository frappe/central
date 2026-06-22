import { test, expect } from './fixtures'

// Declined-card dunning (issue #14). A real off-session charge against a card
// Stripe declines (tok_chargeCustomerFail) fails the Payment Attempt and leaves
// the invoice Open; once the retries are exhausted, dunning takes the invoice
// Overdue and moves the subscription's account standing to Past Due. We walk the
// real dunning state machine with a simulated clock (no waiting calendar days);
// every charge, decline, and transition is real.
test.describe('Dunning (declined card)', () => {
  test('a declined charge goes Overdue and Past Due after the retry window', async ({ page, billing }) => {
    const { team } = await billing.signIn({ scenario: 'ready', currency: 'USD' })
    await billing.saveCard({ team, token: 'tok_chargeCustomerFail' }) // real card that declines on charge
    const { invoice } = await billing.makeInvoice({ team, total: 1180, linkCard: 1 })

    // The waterfall charges the card; Stripe declines → Failed attempt, invoice stays Open.
    const res = await billing.settle({ team, invoice, collect: 1 })
    expect(res.status).toBe('Open')

    // The customer is told the payment failed.
    await page.goto('/legacy-dashboard/settings/notifications')
    await expect(page.getByText('Payment Failure').first()).toBeVisible()

    // Day 7: retries exhausted → invoice Overdue, subscription Past Due.
    const day7 = await billing.dun({ invoice, days: 7 })
    expect(day7.standing).toBe('Past Due')

    await page.goto('/legacy-dashboard/billing/invoices')
    await expect(page.locator('ul.divide-y > li').filter({ hasText: 'Overdue' })).toHaveCount(1)

    await page.goto('/legacy-dashboard/billing/subscriptions')
    await expect(page.getByText('Past Due')).toBeVisible()
  })
})
