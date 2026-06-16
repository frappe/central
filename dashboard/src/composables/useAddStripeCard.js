// Add a card on the Stripe rail (SetupIntent + Stripe Elements). Counterpart to
// the Razorpay path in useAddPaymentMethod.
//
// The PAN is entered in a Stripe Element — a PCI-scoped iframe Stripe hosts; it
// never touches our form or server. Flow (#08):
//   1. initiate_card_setup → an off-session SetupIntent (client_secret) + a
//      pending Payment Method doc.
//   2. confirmCardSetup with the card → Stripe attaches the method to the team's
//      customer and returns the pm_… handle.
//   3. confirm_card → backend runs the micro-charge validation and activates it.
//
// publishableKey + client_secret come from the backend; we never hardcode a key
// (the old Razorpay-only flow passing a Stripe order to Razorpay Checkout is what
// produced the "No key passed" error).

import { ref } from 'vue'
import { loadStripe } from '@stripe/stripe-js'
import { useCall } from 'frappe-ui'
import { API, m } from '@/api/endpoints'
import { successToast, errorToast } from '@/utils/toast'

export function useAddStripeCard({ onDone } = {}) {
  const initiate = useCall({ url: m(API.initiateCardSetup), method: 'POST', immediate: false })
  const confirm = useCall({ url: m(API.confirmCard), method: 'POST', immediate: false })
  const complete = ref(false) // the card field is filled in and valid
  const submitting = ref(false)

  let stripe = null
  let card = null
  let orderPromise = null // the SetupIntent, created in the background while typing

  // Load Stripe.js and mount the card Element straight away. The SetupIntent (a
  // server→Stripe round-trip) is kicked off in parallel and awaited only at
  // submit — so the card field appears instantly instead of waiting on the
  // backend, which is by far the bigger source of perceived load time.
  async function mount(el, { team, publishableKey }) {
    if (!publishableKey) throw new Error('Stripe publishable key missing.')
    stripe = await loadStripe(publishableKey)
    if (!stripe) throw new Error('Stripe.js failed to load.')

    // Swallow here so a reject doesn't become an unhandled rejection if the user
    // cancels before submitting; submit() turns the null into a clean message.
    orderPromise = initiate.submit({ team }).catch(() => null)
    card = stripe.elements().create('card', { hidePostalCode: true })
    // Enable submit only once the card number/expiry/CVC are all valid.
    card.on('change', (e) => (complete.value = !!e.complete))
    card.mount(el)
  }

  // Confirm the SetupIntent with the entered card, then activate it server-side.
  async function submit() {
    if (!stripe || !card || !orderPromise) return
    submitting.value = true
    try {
      const order = await orderPromise // usually already resolved by now
      if (!order?.client_secret) throw new Error('Could not start card setup. Please try again.')

      const { paymentMethod, error: pmError } = await stripe.createPaymentMethod({ type: 'card', card })
      if (pmError) throw pmError

      const { error: setupError } = await stripe.confirmCardSetup(order.client_secret, {
        payment_method: paymentMethod.id,
      })
      if (setupError) throw setupError

      const c = paymentMethod.card
      const res = await confirm.submit({
        payment_method: order.payment_method,
        gateway_method_id: paymentMethod.id,
        display_label: `${capitalise(c.brand)} ····${c.last4}`,
        expiry_month: c.exp_month,
        expiry_year: c.exp_year,
      })
      if (res.status !== 'Active') {
        errorToast("We couldn't verify that card. Please try a different one.")
        return
      }
      successToast('Card added.')
      onDone?.(res)
      return res
    } catch (e) {
      errorToast(e, 'Could not add card.')
    } finally {
      submitting.value = false
    }
  }

  function destroy() {
    card?.destroy()
    card = null
    orderPromise = null
    complete.value = false
  }

  return { mount, submit, destroy, complete, submitting }
}

function capitalise(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s
}
