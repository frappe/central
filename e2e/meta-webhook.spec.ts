import { createHmac } from 'node:crypto'
import { expect, test } from '@playwright/test'

// Meta calls Central's webhook directly. Run against the test site, whose site config holds
// these two values (bench --site v2-tests.localhost set-config <key> <value>):
//   E2E_BASE_URL=http://v2-tests.localhost:8007 yarn playwright test e2e/meta-webhook.spec.ts
// No seed data: the WABA in the body has no route, so Central answers Meta and sends nothing.
const APP_SECRET = process.env.E2E_META_APP_SECRET || 'e2e-meta-app-secret'
const VERIFY_TOKEN = process.env.E2E_META_VERIFY_TOKEN || 'e2e-meta-verify-token'
const WEBHOOK = '/api/method/central.api.meta_webhook.handler'

const SIZES = {
  desktop: { width: 1280, height: 800 },
  phone: { width: 390, height: 844 },
}

const body = JSON.stringify({
  object: 'whatsapp_business_account',
  entry: [{ id: 'waba-without-route', changes: [{ field: 'messages', value: {} }] }],
})
const sign = (secret: string) => `sha256=${createHmac('sha256', secret).update(body).digest('hex')}`

for (const [size, viewport] of Object.entries(SIZES)) {
  test.describe(`Meta webhook relay (${size})`, () => {
    test.use({ viewport })

    test('Meta subscribes only with the verify token', async ({ request }) => {
      const subscribe = (token: string) =>
        request.get(WEBHOOK, {
          params: { 'hub.mode': 'subscribe', 'hub.verify_token': token, 'hub.challenge': 'challenge-7' },
        })

      const ok = await subscribe(VERIFY_TOKEN)
      expect(ok.status()).toBe(200)
      expect(await ok.text()).toBe('challenge-7')
      expect((await subscribe('wrong-token')).status()).toBe(403)
    })

    test('a body signed with the app secret gets 200, any other gets 403', async ({ request }) => {
      const post = (signature: string) =>
        request.post(WEBHOOK, {
          data: body,
          headers: { 'Content-Type': 'application/json', 'X-Hub-Signature-256': signature },
        })

      const signed = await post(sign(APP_SECRET))
      expect(signed.status()).toBe(200)
      expect(await signed.text()).toBe('OK')
      expect((await post(sign('not-the-app-secret'))).status()).toBe(403)
      expect((await post('')).status()).toBe(403)
    })
  })
}
