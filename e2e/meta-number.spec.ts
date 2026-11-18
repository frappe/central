import { expect, test } from '@playwright/test'

// A connect sends the site the new number and its business name, to name the account.
// Runs Central's connect against a fake Meta through central/tests/e2e_meta_number.py:
//   E2E_BASE_URL=http://v2-tests.localhost:8007 yarn playwright test e2e/meta-number.spec.ts
const SIZES = {
  desktop: { width: 1280, height: 800 },
  phone: { width: 390, height: 844 },
}

for (const [size, viewport] of Object.entries(SIZES)) {
  test.describe(`WhatsApp number and name (${size})`, () => {
    test.use({ viewport })

    test('the connect result has the display number and the business name', async ({ request }) => {
      const res = await request.post('/api/method/central.tests.e2e_meta_number.connect_with_fake_meta')
      expect(res.ok(), `${res.status()} ${await res.text()}`).toBeTruthy()
      expect((await res.json()).message).toEqual({
        display_phone_number: '+1 555-010-0001',
        verified_name: 'Acme Store',
      })
    })
  })
}
