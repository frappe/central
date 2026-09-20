import { expect } from '@playwright/test'
import { test as base } from '../fixtures'

const method = (dotted) => `/api/method/${dotted}`

export const test = base.extend({
  billing: async ({ request }, use) => {
    // Call any test-only backend helper (guest, allow_tests-gated) and return its
    // result. Used by the settlement specs to arrange real backend state and to
    // deliver the gateway webhook the local bench can't receive.
    const backend = async (name, form) => {
      const res = await request.post(method(`central.billing.tests.e2e.${name}`), { form })
      expect(res.ok(), `${name} failed: ${res.status()} ${await res.text()}`).toBeTruthy()
      return (await res.json()).message
    }

    // Complete a Razorpay top-up at the gateway boundary: signs the real order with
    // the real test secret and calls the real confirm_topup (see e2e.py). Used by
    // the Razorpay spec, whose hosted sheet can't be automated reliably.
    const finishRazorpay = ({ team, gateway, orderId, amount }) =>
      backend('finish_razorpay_topup', { team, gateway, order_id: orderId, amount })

    // Settlement arrange-helpers (all real backend, no mocks): fund the wallet,
    // attach a real Stripe test card, create a Draft invoice, run the credits→card
    // waterfall, and deliver the success webhook that flips Open → Paid.
    const addCredits = ({ team, amount }) => backend('add_credits', { team, amount })
    // token='tok_chargeCustomerFail' attaches a real card that declines on charge.
    const saveCard = ({ team, token } = {}) => backend('save_test_card', { team, ...(token && { token }) })
    const makeInvoice = ({ team, total = 1180, linkCard = 0 }) =>
      backend('make_invoice', { team, total, link_card: linkCard })
    const settle = ({ team, invoice, collect = 1 }) => backend('settle', { team, invoice, collect })
    // Generate an invoice through the real agentless pipeline (provision → price-lock
    // → generate_draft_invoice), not by fabricating an Invoice doc.
    const generateInvoice = ({ team, monthlyRate = 3000 }) =>
      backend('generate_invoice', { team, monthly_rate: monthlyRate })
    const deliverWebhook = ({ attempt }) => backend('deliver_webhook', { attempt })
    // Run one day of dunning as if `days` had elapsed past the invoice due date.
    const dun = ({ invoice, days = 7 }) => backend('dun', { invoice, days })
    // Refund a captured attempt: destination 'Source' (real Stripe refund) or 'Wallet'.
    const refund = ({ attempt, amount, destination = 'Source' }) =>
      backend('refund', { payment_attempt: attempt, destination, ...(amount && { amount }) })

    // INR rails (e-mandate + UPI Autopay mandate): give the team a trust tier (the
    // UPI ceiling), switch collection mode, run the pre-debit step, and confirm a
    // mandate at the gateway boundary (its hosted recurring sheet can't be automated).
    const setCollectionMode = ({ team, mode }) => backend('set_collection_mode', { team, mode })
    const predebit = ({ invoice }) => backend('predebit', { invoice })
    const finishMandate = ({ paymentMethod, orderId }) =>
      backend('finish_mandate', { payment_method: paymentMethod, order_id: orderId })

    await use({
      finishRazorpay,
      addCredits, saveCard, makeInvoice, settle, deliverWebhook, dun, refund, generateInvoice,
      setCollectionMode, predebit, finishMandate,
    })
  },
})
