import { expect, test } from '@playwright/test'

// A terminated server's WhatsApp Business Accounts stop going to its site. Seeds through the
// allow_tests endpoints in central/tests/e2e_meta.py; no region and no Meta call:
//   E2E_BASE_URL=http://v2-tests.localhost:8007 yarn playwright test e2e/meta-route-cleanup.spec.ts
const SIZES = {
  desktop: { width: 1280, height: 800 },
  phone: { width: 390, height: 844 },
}

// Both sizes seed a Team, and two Teams at once race on the tenant ID series
test.describe.configure({ mode: 'serial' })

for (const [size, viewport] of Object.entries(SIZES)) {
  test.describe(`Meta webhook routes (${size})`, () => {
    test.use({ viewport })

    test('terminating a server deletes the routes to its site', async ({ request }) => {
      const call = async (name: string, form: Record<string, string> = {}) => {
        const res = await request.post(`/api/method/central.tests.e2e_meta.${name}`, { form })
        expect(res.ok(), `${name} failed: ${res.status()} ${await res.text()}`).toBeTruthy()
        return (await res.json()).message
      }
      const { team, server, site, waba_id } = await call('seed_route')
      try {
        expect((await call('get_routed_site', { waba_id })).site).toBe(site)

        await call('terminate_server', { server })

        expect((await call('get_routed_site', { waba_id })).site).toBeNull()
      } finally {
        await call('teardown', { team })
      }
    })
  })
}
