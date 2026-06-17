import { test as base, expect } from '@playwright/test'

// Shared fixtures for the billing e2e suite.
//
// `billing.seed(...)` provisions a fully isolated team + login against the real
// backend (central.billing.tests.e2e.seed) and registers it for teardown after
// the test — so every spec runs in its own sandbox with no cross-test coupling.
// Seeding/teardown go through the test-scoped `request` context, which is a guest
// (its cookie jar is separate from the browser), so they never need a session or
// CSRF token. `billing.login(...)` authenticates the *browser* via `page.request`,
// whose cookies are shared with the page — so after it the dashboard is signed in.

const method = (dotted) => `/api/method/${dotted}`

export const test = base.extend({
  billing: async ({ page, request }, use) => {
    const seeded = []

    async function seed({ scenario = 'profile_pending', currency = 'INR' } = {}) {
      const res = await request.post(method('central.billing.tests.e2e.seed'), {
        form: { scenario, currency },
      })
      expect(res.ok(), `seed failed: ${res.status()} ${await res.text()}`).toBeTruthy()
      const creds = (await res.json()).message
      seeded.push(creds)
      return creds
    }

    // Sign the browser in as a seeded user. Uses page.request so the session
    // cookie lands in the page's context; a subsequent goto renders as that user.
    async function login({ email, password }) {
      const res = await page.request.post(method('login'), { form: { usr: email, pwd: password } })
      expect(res.ok(), `login failed: ${res.status()}`).toBeTruthy()
    }

    // One call for the common path: seed a scenario, then sign in as it.
    async function signIn(opts) {
      const creds = await seed(opts)
      await login(creds)
      return creds
    }

    // Call any test-only backend helper (guest, allow_tests-gated) and return its
    // result. Used by the settlement specs to arrange real backend state and to
    // deliver the gateway webhook the local bench can't receive.
    async function backend(name, form) {
      const res = await request.post(method(`central.billing.tests.e2e.${name}`), { form })
      expect(res.ok(), `${name} failed: ${res.status()} ${await res.text()}`).toBeTruthy()
      return (await res.json()).message
    }

    // Complete a Razorpay top-up at the gateway boundary: signs the real order with
    // the real test secret and calls the real confirm_topup (see e2e.py). Used by
    // the Razorpay spec, whose hosted sheet can't be automated reliably.
    const finishRazorpay = ({ team, gateway, orderId, amount }) =>
      backend('finish_razorpay_topup', { team, gateway, order_id: orderId, amount })

    // Settlement arrange-helpers (all real backend, no mocks): fund the wallet,
    // attach a real Stripe test card, create a Draft invoice, run the credits→card
    // waterfall, and deliver the success webhook that flips Open → Paid.
    const addCredits = ({ team, amount }) => backend('add_credits', { team, amount })
    // token='tok_chargeCustomerFail' attaches a real card that declines on charge.
    const saveCard = ({ team, token } = {}) => backend('save_test_card', { team, ...(token && { token }) })
    const makeInvoice = ({ team, total = 1180, linkCard = 0 }) =>
      backend('make_invoice', { team, total, link_card: linkCard })
    const settle = ({ team, invoice, collect = 1 }) => backend('settle', { team, invoice, collect })
    const deliverWebhook = ({ attempt }) => backend('deliver_webhook', { attempt })
    // Run one day of dunning as if `days` had elapsed past the invoice due date.
    const dun = ({ invoice, days = 7 }) => backend('dun', { invoice, days })

    // INR rails (e-mandate + UPI Autopay mandate): give the team a trust tier (the
    // UPI ceiling), switch collection mode, run the pre-debit step, and confirm a
    // mandate at the gateway boundary (its hosted recurring sheet can't be automated).
    const setTrustTier = ({ team, maxSpend = 50000 }) => backend('set_trust_tier', { team, max_spend: maxSpend })
    const setCollectionMode = ({ team, mode }) => backend('set_collection_mode', { team, mode })
    const predebit = ({ invoice }) => backend('predebit', { invoice })
    const finishMandate = ({ paymentMethod, orderId }) =>
      backend('finish_mandate', { payment_method: paymentMethod, order_id: orderId })

    await use({
      seed, login, signIn, finishRazorpay,
      addCredits, saveCard, makeInvoice, settle, deliverWebhook, dun,
      setTrustTier, setCollectionMode, predebit, finishMandate,
    })

    // Best-effort teardown of everything this test seeded (guest context).
    for (const c of seeded) {
      await request
        .post(method('central.billing.tests.e2e.teardown'), { form: { team: c.team, email: c.email } })
        .catch(() => {})
    }
  },
})

export { expect }
