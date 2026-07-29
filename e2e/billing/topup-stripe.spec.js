import { test, expect } from './fixtures'
import { fillStripeCard } from './helpers/stripe.js'

// The hero no-mock flow: a USD team tops up its wallet through the *real* Stripe
// test sandbox. The seed completes the billing profile (un-gating money movement)
// in USD, whose default gateway is Stripe — so "Top up" deterministically routes
// to the embedded Stripe card Element. We type the 4242 test card into Stripe's
// own iframe, confirm a genuine test-mode PaymentIntent, and the backend credits
// the wallet only after Stripe confirms the charge. Nothing is stubbed.
// TODO: legacy dashboard removed; billing/credits isn't ported to console yet.
// Un-skip once console has it.
test.describe.skip('Wallet top-up (Stripe)', () => {
  test('tops up a USD wallet via a real Stripe test-mode PaymentIntent', async ({ page, billing }) => {
    await billing.signIn({ scenario: 'ready', currency: 'USD' })

    await page.goto('/legacy-dashboard/billing/credits')

    // Wallet starts empty.
    await expect(page.getByText('Wallet balance')).toBeVisible()
    await expect(page.getByText('No credit activity yet.')).toBeVisible()

    // Amount step.
    await page.getByRole('button', { name: 'Top up' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText('Top up wallet')).toBeVisible()
    await dialog.getByRole('button', { name: '$1,000' }).click() // preset
    await dialog.getByRole('button', { name: 'Continue to payment' }).click()

    // Stripe card phase: fill the real Stripe Element, then pay.
    await fillStripeCard(dialog, { number: '4242424242424242', expiry: '12 / 34', cvc: '123' })
    const pay = dialog.getByRole('button', { name: /^Pay/ })
    await expect(pay).toBeEnabled({ timeout: 20_000 }) // enables once the card validates
    await pay.click()

    // Wallet credited only after Stripe confirms — assert the user-visible result.
    // (exact: true avoids also matching the aria-live announcer's prefixed copy.)
    await expect(page.getByText('Wallet topped up.', { exact: true })).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText('No credit activity yet.')).toHaveCount(0)
    // A credit-history row records the top-up against its real Stripe PaymentIntent id.
    await expect(page.getByText(/Wallet top-up \(pi_/)).toBeVisible()
    // Balance tile now reflects the $1,000 top-up.
    await expect(page.getByText('1,000').first()).toBeVisible()
  })
})
