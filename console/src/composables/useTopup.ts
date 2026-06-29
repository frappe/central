// Wallet top-up — prepaid customers add credit through a real gateway order.
// Ported from the legacy dashboard.
//
// Flow (webhook/confirm-truth, no magic crediting):
//   1. begin(amount)  → create_topup_order makes a real gateway order.
//   2. Razorpay finishes in its hosted sheet right here; Stripe needs an in-app
//      card field, so begin() returns { card: true } and the dialog calls
//      mountCard()/pay(); PayPal returns { paypal: true } and mounts Buttons.
//   3. confirm_topup  → backend verifies the gateway actually took the money,
//      then credits the wallet in the team's own currency.
//
// The PAN is entered in a Stripe Element (a PCI-scoped iframe Stripe hosts); the
// India-export billing address rides on the PaymentIntent from the Billing
// Profile (server-side), so the customer is never re-asked for it.

import { computed, ref } from 'vue'
import { loadStripe, type Stripe, type StripeCardElement } from '@stripe/stripe-js'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { openRazorpayCheckout, mountPayPalButtons, type GatewayOrder } from '@/lib/gateway'
import { successToast, errorToast } from '@/lib/toast'

interface BeginResult {
  card?: boolean
  paypal?: boolean
}

export function useTopup({ onDone }: { onDone?: (res: unknown) => void } = {}) {
  const { activeTeam } = useSession()
  const createOrder = useCall<GatewayOrder, Record<string, unknown>>({
    url: method(API.createTopupOrder),
    immediate: false,
  })
  const confirm = useCall<unknown, Record<string, unknown>>({
    url: method(API.confirmTopup),
    immediate: false,
  })

  // Stripe card-phase state — populated only once a Stripe order needs a card.
  const cardComplete = ref(false)
  const submitting = ref(false)
  let stripe: Stripe | null = null
  let card: StripeCardElement | null = null
  let order: GatewayOrder | null = null

  // Create the gateway order, then resolve by rail:
  //  - Stripe → { card: true }: dialog mounts the card Element.
  //  - Paypal → { paypal: true }: dialog mounts PayPal Buttons (ADR 0007).
  //  - Razorpay → collected in its hosted sheet, the whole top-up resolves here.
  // `payMethod` is 'paypal' for an international PayPal top-up.
  async function begin(amount: number, payMethod?: string): Promise<BeginResult> {
    try {
      await createOrder.submit({ team: activeTeam.value, amount, method: payMethod })
      order = createOrder.data
      if (!order) throw new Error('Could not start the top-up.')
      if (order.adapter_key === 'Stripe') return { card: true }
      if (order.adapter_key === 'Paypal') return { paypal: true }

      const handles = await openRazorpayCheckout(order, {
        name: 'Central',
        description: 'Wallet top-up',
        displayPayPal: order.display_paypal,
      })
      await confirm.submit({
        team: activeTeam.value,
        amount: order.amount,
        gateway: order.gateway,
        ...handles,
      })
      finish(confirm.data)
    } catch (e) {
      if ((e as Error)?.message !== 'cancelled') errorToast(e, 'Top-up could not be completed.')
    }
    return { card: false }
  }

  // Render PayPal Buttons for the order begin() created. On approval we capture
  // the order server-side (confirm_topup) and credit what PayPal actually took.
  async function mountPayPal(el: Element): Promise<void> {
    if (!order) return
    await mountPayPalButtons(el, order, {
      onApprove: async (paypalOrderId: string) => {
        submitting.value = true
        try {
          await confirm.submit({
            team: activeTeam.value,
            amount: order!.amount,
            gateway: order!.gateway,
            paypal_order_id: paypalOrderId,
          })
          finish(confirm.data)
        } catch (e) {
          errorToast(e, 'Top-up could not be completed.')
        } finally {
          submitting.value = false
        }
      },
      onError: (e) => errorToast(e, 'PayPal could not start.'),
    })
  }

  // Mount the Stripe card Element for the order begin() created.
  async function mountCard(el: string | HTMLElement): Promise<void> {
    if (!order?.publishable_key) throw new Error('Stripe publishable key missing.')
    stripe = await loadStripe(order.publishable_key)
    if (!stripe) throw new Error('Stripe.js failed to load.')
    card = stripe.elements().create('card', { hidePostalCode: true })
    card.on('change', (e) => (cardComplete.value = !!e.complete))
    card.mount(el)
  }

  // Confirm the PaymentIntent with the entered card, then credit server-side from
  // what Stripe actually charged.
  async function pay(): Promise<unknown> {
    if (!stripe || !card || !order?.client_secret) return
    submitting.value = true
    try {
      const { paymentIntent, error } = await stripe.confirmCardPayment(order.client_secret, {
        payment_method: { card },
      })
      if (error) throw error
      if (paymentIntent?.status !== 'succeeded') throw new Error('Payment was not completed.')

      await confirm.submit({
        team: activeTeam.value,
        amount: order.amount,
        gateway: order.gateway,
        payment_intent: paymentIntent.id,
      })
      finish(confirm.data)
      return confirm.data
    } catch (e) {
      errorToast(e, 'Top-up could not be completed.')
    } finally {
      submitting.value = false
    }
  }

  function finish(res: unknown): void {
    successToast('Wallet topped up.')
    onDone?.(res)
  }

  function destroy(): void {
    card?.destroy()
    card = null
    stripe = null
    order = null
    cardComplete.value = false
  }

  return {
    begin,
    mountCard,
    mountPayPal,
    pay,
    destroy,
    cardComplete,
    submitting,
    loading: computed(() => createOrder.loading || confirm.loading),
  }
}
