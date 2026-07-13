import { test, expect } from './fixtures'

// INR wallet top-up over the Razorpay rail. The hosted Razorpay sheet loads
// hCaptcha + fraud frames and a cross-origin 3DS simulator, so it can't be clicked
// through reliably — we drive the real UI up to the point where the *genuine*
// Razorpay test sheet opens against a *real* test order, then finish the no-mock
// path at the gateway boundary: a test-only endpoint signs that real order with
// the real test secret (the exact HMAC Razorpay's callback returns) and calls the
// real confirm_topup, which verifies the signature and credits the wallet. The
// only synthetic value is the payment-id string. See e2e.py:finish_razorpay_topup.
// TODO: legacy dashboard removed; billing/credits isn't ported to console yet.
// Un-skip once console has it.
test.describe.skip('Wallet top-up (Razorpay)', () => {
  test('opens the real Razorpay sheet for an INR order and credits the wallet', async ({ page, billing }) => {
    const { team } = await billing.signIn({ scenario: 'ready', currency: 'INR' })

    await page.goto('/legacy-dashboard/billing/credits')
    await expect(page.getByText('No credit activity yet.')).toBeVisible()

    // Capture the REAL Razorpay order create_topup_order mints on "Continue".
    const orderResp = page.waitForResponse((r) => r.url().includes('create_topup_order'))
    await page.getByRole('button', { name: 'Top up' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Amount').fill('1000')
    await dialog.getByRole('button', { name: 'Continue to payment' }).click()

    const order = (await (await orderResp).json()).data
    expect(order.adapter_key).toBe('Razorpay') // INR routes to a Razorpay rail
    expect(order.order_id).toMatch(/^order_/) // a genuine test-mode order id

    // The genuine Razorpay test sheet opens against that real order.
    await expect
      .poll(
        () => page.frames().some((f) => /api\.razorpay\.com\/v1\/checkout\/public/.test(f.url())),
        { timeout: 20_000 },
      )
      .toBe(true)

    // Finish the no-mock path at the gateway boundary (real secret, real signature,
    // real confirm_topup).
    await billing.finishRazorpay({ team, gateway: order.gateway, orderId: order.order_id, amount: 1000 })

    // The wallet now reflects the credited ₹1,000 top-up, keyed on the payment id.
    await page.goto('/legacy-dashboard/billing/credits')
    await expect(page.getByText('No credit activity yet.')).toHaveCount(0)
    await expect(page.getByText(/Wallet top-up \(pay_/)).toBeVisible()
    await expect(page.getByText('1,000').first()).toBeVisible()
  })
})
