import { test as base, expect } from '@playwright/test'

const method = (dotted) => `/api/method/${dotted}`

export const test = base.extend({
  users: async ({ page, request }, use) => {
    const seeded = []

    const seed = async ({ scenario = 'profile_pending', currency = 'INR' } = {}) => {
      const res = await request.post(method('central.billing.tests.e2e.seed'), {
        form: { scenario, currency },
      })
      expect(res.ok(), `seed failed: ${res.status()} ${await res.text()}`).toBeTruthy()
      const creds = (await res.json()).message
      seeded.push(creds)
      return creds
    }

    const login = async ({ email, password }) => {
      const res = await page.request.post(method('login'), { form: { usr: email, pwd: password } })
      expect(res.ok(), `login failed: ${res.status()}`).toBeTruthy()
    }

    const signIn = async (options) => {
      const creds = await seed(options)
      await login(creds)
      return creds
    }

    await use({ seed, login, signIn })

    for (const creds of seeded) {
      await request
        .post(method('central.billing.tests.e2e.teardown'), { form: { team: creds.team, email: creds.email } })
        .catch(() => {})
    }
  },
})

export { expect }
