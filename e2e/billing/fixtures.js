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

    // Complete a Razorpay top-up at the gateway boundary: signs the real order with
    // the real test secret and calls the real confirm_topup (see e2e.py). Used by
    // the Razorpay spec, whose hosted sheet can't be automated reliably.
    async function finishRazorpay({ team, gateway, orderId, amount }) {
      const res = await request.post(method('central.billing.tests.e2e.finish_razorpay_topup'), {
        form: { team, gateway, order_id: orderId, amount },
      })
      expect(res.ok(), `finish_razorpay failed: ${res.status()} ${await res.text()}`).toBeTruthy()
      return (await res.json()).message
    }

    await use({ seed, login, signIn, finishRazorpay })

    // Best-effort teardown of everything this test seeded (guest context).
    for (const c of seeded) {
      await request
        .post(method('central.billing.tests.e2e.teardown'), { form: { team: c.team, email: c.email } })
        .catch(() => {})
    }
  },
})

export { expect }
