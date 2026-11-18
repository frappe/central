import { expect, test } from '@playwright/test'

// A site stops Central sending a WhatsApp Business Account's Meta webhooks through its Pilot.
// The X-Pilot-Site header names the site only after Pilot's credential is checked, so the header
// alone opens nothing. No seed data and no call to Meta.
const SIZES = {
  desktop: { width: 1280, height: 800 },
  phone: { width: 390, height: 844 },
}

for (const [size, viewport] of Object.entries(SIZES)) {
  test.describe(`WhatsApp disconnect (${size})`, () => {
    test.use({ viewport })

    test('central.api.oauth.disconnect asks a site for its Pilot credential', async ({ request }) => {
      const response = await request.post('/api/method/central.api.oauth.disconnect', {
        data: { waba_id: '1029384756' },
        headers: { 'X-Pilot-Site': 'any-site.localhost' },
      })
      expect(response.status()).toBe(401)
    })

    test('central.api.oauth.relay_token for meta asks a site for its Pilot credential', async ({
      request,
    }) => {
      const response = await request.post('/api/method/central.api.oauth.relay_token', {
        data: { provider: 'meta', grant_type: 'authorization_code', code: 'x' },
        headers: { 'X-Pilot-Site': 'any-site.localhost' },
      })
      expect(response.status()).toBe(401)
    })
  })
}
