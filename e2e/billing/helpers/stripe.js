import { expect } from '@playwright/test'

// Stripe's PCI-scoped card Element is a cross-origin iframe; we can't read its
// internals, but we CAN type into its inputs by frame name. These are real
// keystrokes into the real (test-mode) Stripe Element — the same path a customer
// takes — so the PaymentIntent that follows is genuine, nothing stubbed.

// 4242… is Stripe's universal test card that always succeeds. The combined Card
// Element (elements().create('card')) renders one iframe holding the number,
// expiry and CVC inputs (postal hidden via hidePostalCode).
export const TEST_CARD = { number: '4242424242424242', expiry: '12 / 34', cvc: '123' }

// Fill the Stripe card Element mounted inside `root` (the dialog/card container).
// Waits for the iframe to attach, then types each field. Returns once filled so
// the caller can assert the gateway-confirm step.
export async function fillStripeCard(root, card = TEST_CARD) {
  const frame = root.frameLocator('iframe[title*="card"], iframe[name^="__privateStripeFrame"]')
  const number = frame.locator('[name="cardnumber"], [name="number"]').first()
  await expect(number).toBeVisible({ timeout: 20_000 })
  await number.fill(card.number)
  await frame.locator('[name="exp-date"], [name="expiry"]').first().fill(card.expiry)
  await frame.locator('[name="cvc"]').first().fill(card.cvc)
}
