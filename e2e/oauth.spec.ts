import { expect, test } from '@playwright/test'

// central.api.oauth is the sign-in relay path for every provider; central.api.email_oauth
// is its old path, which live sites and the mail providers' registered redirect still use.
// Both must answer the same way. No seed data and no provider is called.
const PATHS = ['central.api.oauth', 'central.api.email_oauth']
const SIZES = {
  desktop: { width: 1280, height: 800 },
  phone: { width: 390, height: 844 },
}

for (const [size, viewport] of Object.entries(SIZES)) {
  test.describe(`sign-in relay (${size})`, () => {
    test.use({ viewport })

    for (const path of PATHS) {
      test(`${path} asks a site for its Pilot credential`, async ({ request }) => {
        for (const method of ['start', 'get_active_providers', 'relay_token']) {
          const response = await request.post(`/api/method/${path}.${method}`)
          expect(response.status(), method).toBe(401)
        }
      })

      test(`${path}.callback tells the browser an unknown sign-in has expired`, async ({ page }) => {
        const response = await page.goto(`/api/method/${path}.callback?state=unknown&code=x`, {
          waitUntil: 'domcontentloaded',
        })

        expect(response?.status()).toBe(400)
        await expect(page.getByText('Link expired').first()).toBeVisible()
        await expect(page.getByText('Please start again from your site.')).toBeVisible()
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth > window.innerWidth,
        )
        expect(overflow).toBe(false)
      })
    }
  })
}
