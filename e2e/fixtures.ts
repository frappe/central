import { test as base, expect } from '@playwright/test'

const method = (dotted) => `/api/method/${dotted}`

export const test = base.extend({
  teams: async ({ page, request, users }, use) => {
    const api = (endpoint) => method(`central.api.teams.${endpoint}`)

    const addMember = async ({ owner, role = 'Developer' }) => {
      const member = await users.seed()

      const invite = await page.request.post(api('invite_team_member'), {
        form: { team: owner.team, email: member.email, role },
      })
      const invitation = (await invite.json()).message

      await users.login(member)
      await page.request.post(api('accept_invitation'), { form: { invitation } })
      await users.login(owner)

      return member
    }

    const setTrustTier = async ({ team, maxSpend = 50000 }) => {
      const res = await request.post(method('central.billing.tests.e2e.set_trust_tier'), {
        form: { team, max_spend: maxSpend },
      })
      expect(res.ok(), `set_trust_tier failed: ${res.status()}`).toBeTruthy()
      return (await res.json()).message
    }

    await use({ addMember, setTrustTier })
  },

  users: async ({ page, request }, use) => {
    const seeded = []

    const seed = async ({ scenario = 'profile_pending', currency = 'INR' } = {}) => {
      let creds

      await expect(async () => {
        const res = await request.post(method('central.billing.tests.e2e.seed'), {
          form: { scenario, currency },
        })
        expect(res.ok(), `seed failed: ${res.status()} ${await res.text()}`).toBeTruthy()
        creds = (await res.json()).message
      }).toPass({ timeout: 5_000 })

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
