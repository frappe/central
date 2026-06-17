# End-to-end suite (no mocks)

Playwright specs that drive the **real** Frappe-UI dashboard against a **running
`central.local` bench** and the **real gateway test sandboxes**. Nothing is
stubbed: a top-up creates a genuine Stripe test-mode `PaymentIntent`, the wallet is
credited only after the gateway confirms, and every read renders from real DocTypes.

## Layout

Specs are grouped by domain, each domain owning its fixtures + helpers so the
seams stay independent:

```
e2e/
  billing/            # billing dashboard flows (this suite)
    fixtures.js       # `billing` fixture: seed/login/teardown + finishRazorpay
    helpers/stripe.js # fill the Stripe card Element
    *.spec.js
  # iam/              # (future) IAM flows — its own fixtures + seed endpoint
```

Playwright discovers `**/*.spec.js` under `e2e/` recursively, so a new domain is
just a new subfolder. Each domain wires its own test-only seed endpoint under
`central/<domain>/tests/e2e.py`; billing's lives at `central/billing/tests/e2e.py`.

## What billing covers

| Spec | Flow | No-mock surface |
| --- | --- | --- |
| `onboarding.spec.js` | First-run wizard completes the Billing Profile | real `save_billing_profile` |
| `topup-stripe.spec.js` | USD wallet top-up via the embedded Stripe card Element | **real Stripe test-mode PaymentIntent** (4242 card) |
| `topup-razorpay.spec.js` | INR wallet top-up — real Razorpay sheet opens, finished at the gateway boundary | **real Razorpay test order + real signature**, real `confirm_topup` |
| `invoices.spec.js` | Invoice list + detail (line items, tax block) | real `Invoice` docs |
| `settlement.spec.js` | Credits-only, partial credits + card, and the "Pay" button | **real credits→card waterfall**, real off-session PaymentIntent, real `apply_webhook` |

### Settlement & the webhook boundary

`settlement.spec.js` runs the real credits-then-card waterfall (`open_and_collect`):
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

- The bench must already be running and serving the dashboard on
  `http://central.local:8011` (`central.local` is in `/etc/hosts`).
- `central.local` must have `allow_tests: true` (it does) — this gates the
  test-only seed endpoints. They are unreachable on any site without it.
- Real **test-mode** gateway keys in `sites/common_site_config.json`
  (`stripe_secret_key`/`stripe_publishable_key` = `sk_test_`/`pk_test_`,
  `razorpay_key_id`/`razorpay_key_secret` = `rzp_test`). Stripe specs need
  outbound network to `js.stripe.com` and the Stripe API.

### Starting the bench

```bash
cd ../../..            # the bench root (cenral-bench)
# node >= 24 must be on PATH or honcho's `watch` process crashes and tears the
# whole bench down — prepend the nvm node if your shell defaults to an older one:
PATH="$HOME/.nvm/versions/node/v24.16.0/bin:$PATH" bench start
```

## Running

```bash
cd apps/central
yarn test:e2e            # headless
yarn test:e2e:headed     # watch it drive a real browser
yarn test:e2e:report     # open the last HTML report

# target the host explicitly:
E2E_BASE_URL=http://central.local:8011 npx playwright test
```

Specs run **serially** (`workers: 1`) on purpose — the gateway sandboxes are
shared, rate-limited, mutable state, so two specs must never confirm a payment at
the same instant.

## How isolation works

Each spec provisions its own sandbox through the test-only backend endpoints in
`central/billing/tests/e2e.py`:

- `seed(scenario, currency)` creates a fresh user (known password) and seeds data
  onto the personal team Central bootstraps for them — so they own exactly one
  team and it is the deterministic `whoami` default. Scenarios:
  `profile_pending` → `ready` (complete profile) → `with_invoices`.
- `teardown(team, email)` deletes everything that spec created.

The `billing` fixture in `billing/fixtures.js` calls these for you
(`billing.signIn(...)`) and tears down in `afterEach`, so a full run leaves **zero**
residue. Seed/teardown run as guest over HTTP and elevate to Administrator behind
the `allow_tests` gate.

## Adding a spec

1. Add a scenario branch to `seed()` in `central/billing/tests/e2e.py` if you need
   new backing data. **Restart the web worker** after editing it (the dev server
   caches imported modules).
2. Add the spec under `e2e/billing/`. `import { test, expect } from './fixtures'`,
   call `await billing.signIn({...})`, `page.goto('/dashboard/...')`, and assert on
   user-visible state.
3. For Stripe card entry, use `fillStripeCard()` from `./helpers/stripe.js`.
