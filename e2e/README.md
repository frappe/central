# End-to-end suite (no mocks)

Playwright specs that drive the **real** Frappe-UI dashboard against a **running
`central.localhost` bench** and the **real gateway test sandboxes**. Nothing is
stubbed: a top-up creates a genuine Stripe test-mode `PaymentIntent`, the wallet is
credited only after the gateway confirms, and every read renders from real DocTypes.

## Layout

```
e2e/
  fixtures.ts             # shared `users` (seed, login, signIn, teardown) and `teams` fixtures
  notifications.spec.ts
  billing/
    fixtures.ts           # adds the `billing` payment helpers (finishRazorpay and others)
    helpers/stripe.ts     # fills the Stripe card Element
    *.spec.ts
  servers/ settings/ team/  # *.spec.ts per area
```

Playwright discovers every `*.spec.ts` under `e2e/`. All areas seed their data through the test-only endpoints in `central/billing/tests/e2e.py`, which `e2e/fixtures.ts` calls.

## What the suite covers

These specs run:

| Area | Specs |
| --- | --- |
| Billing | `invoices`, `limits`, `overview`, `profile`, `projects`, `reports` |
| Servers | `servers/list`, `servers/new` |
| Team | `team/invite`, `team/manage`, `team/roles`, `team/settings`, `team/switch` |
| Settings | `settings/profile` |
| Notifications | `notifications` |

These billing specs are skipped (`test.describe.skip`) until the console has the flow again. Each one still holds the no-mock path described below:

| Spec | Flow | No-mock surface |
| --- | --- | --- |
| `onboarding.spec.ts` | First-run wizard completes the Billing Profile | real `save_billing_profile` |
| `topup-stripe.spec.ts` | USD wallet top-up via the embedded Stripe card Element | **real Stripe test-mode PaymentIntent** (4242 card) |
| `topup-razorpay.spec.ts` | INR wallet top-up, finished at the gateway boundary | **real Razorpay test order and signature**, real `confirm_topup` |
| `settlement.spec.ts` | Credits only, partial credits and card, and the Pay button | **real credits-then-card waterfall**, real off-session PaymentIntent, real `apply_webhook` |
| `mandate-upi.spec.ts` | UPI Autopay mandate setup (INR) | **real Razorpay recurring order and signature**, real `confirm_mandate` |
| `emandate.spec.ts` | INR e-mandate pre-debit notice and the ₹15,000 Action Required fork | real `schedule_predebit` and `collection_mode` |
| `dunning.spec.ts` | Declined card becomes Overdue and Past Due after the retry window | **real Stripe decline** and the real dunning state machine (simulated clock) |
| `refunds.spec.ts` | Full dispute refunds the source; partial overcharge refunds the wallet | **real Stripe refund** and the real credit ledger |
| `invoice-generation.spec.ts` | Provision a subscription, then generate its invoice | real `provision_subscription` and `generate_draft_invoice` |

The next three sections describe the skipped specs.

### INR rails (e-mandate + UPI Autopay)

`emandate.spec.ts` is fully real (no gateway): it drives `schedule_predebit`, asserting
the **pre-debit notice** for a ≤₹15,000 bill and the **Action Required** banner + the
prepaid/manual-checkout choice for a bill over the silent-debit ceiling. `mandate-upi.spec.ts`
sets up a UPI Autopay mandate — UPI authorises through Razorpay's hosted recurring sheet
(same bot protection as the top-up), so it opens the **real recurring order/sheet** from the
UI and confirms at the gateway boundary (`e2e.py:finish_mandate`: real checkout-callback
signature; only the recurring **token id** is synthetic, since Razorpay issues one only via
the bank/UPI auth flow). The successful recurring **debit** of an INR invoice isn't covered
end-to-end for the same reason — it needs a real authorised token.

### Settlement & the webhook boundary

`settlement.spec.ts` runs the real credits-then-card waterfall (`open_and_collect`):
credits apply first; if they cover the bill it is `Paid` with no charge, otherwise
the remainder is charged to a **real Stripe test card** (attached off-session via
`tok_visa`) through a genuine PaymentIntent. The `Open → Paid` flip is webhook-only
in production, and a local bench can't receive live webhooks — so the spec delivers
it by building a `Webhook Event` from the **real captured transaction id** and
running the **real** `apply_webhook` (`e2e.py:deliver_webhook`). Only the HTTP
signature check (a separate gate, unit-tested) is skipped; the charge, the txn id,
and the settlement logic are all real.

### Gateway automation note

**Stripe Elements** automates cleanly — we type the 4242 test card straight into
Stripe's iframe and confirm a genuine PaymentIntent. **Razorpay's hosted Checkout**
does not: it loads invisible hCaptcha, Sardine fraud signals and a cross-origin 3DS
simulator that resist (and detect) browser automation. So the Razorpay spec drives
the real UI until the **genuine Razorpay test sheet opens against a real test
order**, then completes the no-mock path at the gateway boundary —
`e2e.py:finish_razorpay_topup` signs that real order with the **real test secret**
(the exact HMAC Razorpay's callback returns) and calls the **real** `confirm_topup`,
which verifies the signature and credits the wallet. Only the `pay_…` id string is
synthetic, because minting a Razorpay-issued one needs its bot-gated sheet.

## Prerequisites

- The bench must already be running and serving the dashboard. The suite targets `http://central.localhost:8000` by default. Set `E2E_BASE_URL` for another site or port. See the [README](../README.md) for the bench setup.
- The site must have `allow_tests: true`. This gates the test-only seed endpoints. They are unreachable on any site without it.
- The site needs the catalog and gateway records. Run the demo seed first: `pilot frappe --site central.localhost execute central.billing.demo.demo_scenarios.seed`.
- Real **test-mode** gateway keys in `sites/common_site_config.json` (`stripe_secret_key`/`stripe_publishable_key` = `sk_test_`/`pk_test_`, `razorpay_key_id`/`razorpay_key_secret` = `rzp_test`). Stripe specs need outbound network to `js.stripe.com` and the Stripe API.

## CI

`.github/workflows/e2e.yml` runs the suite on push to `develop`, on manual dispatch, and on same-repository pull requests that change `dashboard/`, `e2e/`, `playwright.config.ts`, or the workflow. Fork pull requests are skipped because they do not get the gateway secrets.

It boots a bench + `test_site`, builds the SPA, seeds the catalog/gateways, serves
on port 8000, installs Playwright, and runs the suite, uploading the HTML report as
an artifact. **Required repo secrets** (test-mode keys): `STRIPE_SECRET_KEY`,
`STRIPE_PUBLISHABLE_KEY`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` — the job fails
fast with a clear message if they're absent.

## Running

```bash
cd apps/central
yarn test:e2e            # headless
yarn test:e2e:headed     # watch it drive a real browser
yarn test:e2e:report     # open the last HTML report

# target the host explicitly:
E2E_BASE_URL=http://central.localhost:8000 npx playwright test
```

Specs run in parallel: 4 workers locally and 2 in CI. Each spec seeds its own user and team, so specs do not share data.

## How isolation works

Each spec provisions its own sandbox through the test-only backend endpoints in
`central/billing/tests/e2e.py`:

- `seed(scenario, currency)` creates a fresh user (known password) and one team
  they own, with its console onboarding skipped. The team is the deterministic
  `whoami` default. Scenarios:
  `profile_pending` → `ready` (complete profile) → `with_invoices`.
- `teardown(team, email)` deletes everything that spec created.

The `users` fixture in `e2e/fixtures.ts` calls these for you
(`users.signIn(...)`) and tears down after each test, so a full run leaves **zero**
residue. Seed/teardown run as guest over HTTP and elevate to Administrator behind
the `allow_tests` gate.

## Adding a spec

1. Add a scenario branch to `seed()` in `central/billing/tests/e2e.py` if you need
   new backing data. **Restart the web worker** after editing it (the dev server
   caches imported modules).
2. Add the spec under its area folder, such as `e2e/team/`, and import `test` from `'../fixtures'` and `expect` from `'@playwright/test'`.
   Billing specs import from `./fixtures` instead, which adds the `billing` payment helpers. Then
   call `await users.signIn({...})`, `page.goto('/dashboard/...')`, and assert on
   user-visible state.
3. For Stripe card entry, use `fillStripeCard()` from `./helpers/stripe.ts`.
