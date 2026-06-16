// Wallet top-up — prepaid customers add credit through a real gateway order.
//
// Flow (webhook/confirm-truth, no magic crediting):
//   1. begin(amount)  → create_topup_order makes a real gateway order.
//   2. Razorpay finishes in its hosted sheet right here; Stripe needs an in-app
//      card field, so begin() returns { card: true } and the dialog calls
//      mountCard()/pay() — no hosted-Checkout redirect.
//   3. confirm_topup  → backend verifies the gateway actually took the money,
//      then credits the wallet in the team's own currency.
//
// The PAN is entered in a Stripe Element (a PCI-scoped iframe Stripe hosts); it
// never touches our form or server. The India-export billing address rides on
// the PaymentIntent from the Billing Profile (set server-side), so the customer
// is never asked to re-enter an address we already hold.

import { computed, ref } from 'vue'
import { loadStripe } from '@stripe/stripe-js'
import { useCall } from 'frappe-ui'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { openRazorpayCheckout } from '@/utils/gateway'
import { successToast, errorToast } from '@/utils/toast'

export function useTopup({ onDone } = {}) {
  const { currentTeam } = useTeam()
  const createOrder = useCall({ url: m(API.createTopupOrder), method: 'POST', immediate: false })
  const confirm = useCall({ url: m(API.confirmTopup), method: 'POST', immediate: false })

  // Stripe card-phase state — populated only once a Stripe order needs a card.
  const cardComplete = ref(false) // the card field is filled in and valid
  const submitting = ref(false)
  let stripe = null
  let card = null
  let order = null

  // Create the gateway order. Razorpay collects payment in its hosted sheet and
  // resolves the whole top-up here; Stripe returns { card: true } so the dialog
  // can mount the card Element for the order we just created.
  async function begin(amount) {
    try {
      order = await createOrder.submit({ team: currentTeam.value, amount })
      if (order.adapter_key === 'Stripe') return { card: true }

      const handles = await openRazorpayCheckout(order, { name: 'Central', description: 'Wallet top-up' })
      const res = await confirm.submit({
        team: currentTeam.value,
        amount: order.amount,
        gateway: order.gateway,
        ...handles,
      })
      finish(res)
    } catch (e) {
      if (e?.message !== 'cancelled') errorToast(e, 'Top-up could not be completed.') // closed sheet = no-op
    }
    return { card: false }
  }

  // Mount the Stripe card Element for the order begin() created.
  async function mountCard(el) {
    if (!order?.publishable_key) throw new Error('Stripe publishable key missing.')
    stripe = await loadStripe(order.publishable_key)
    if (!stripe) throw new Error('Stripe.js failed to load.')
    card = stripe.elements().create('card', { hidePostalCode: true })
    card.on('change', (e) => (cardComplete.value = !!e.complete))
    card.mount(el)
  }

  // Confirm the PaymentIntent with the entered card, then credit server-side
  // from what Stripe actually charged.
  async function pay() {
    if (!stripe || !card || !order?.client_secret) return
    submitting.value = true
    try {
      const { paymentIntent, error } = await stripe.confirmCardPayment(order.client_secret, {
        payment_method: { card },
      })
      if (error) throw error
      if (paymentIntent?.status !== 'succeeded') throw new Error('Payment was not completed.')

      const res = await confirm.submit({
        team: currentTeam.value,
        amount: order.amount,
        gateway: order.gateway,
        payment_intent: paymentIntent.id,
      })
      finish(res)
      return res
    } catch (e) {
      errorToast(e, 'Top-up could not be completed.')
    } finally {
      submitting.value = false
    }
  }

  function finish(res) {
    successToast('Wallet topped up.')
    onDone?.(res)
  }

  function destroy() {
    card?.destroy()
    card = null
    stripe = null
    order = null
    cardComplete.value = false
  }

  return {
    begin,
    mountCard,
    pay,
    destroy,
    cardComplete,
    submitting,
    // Order creation or server confirm in flight counts as busy.
    loading: computed(() => createOrder.loading || confirm.loading),
  }
}
