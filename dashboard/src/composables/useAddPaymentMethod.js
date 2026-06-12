// Add a recurring payment method (Razorpay path: UPI Autopay mandate or card token).
//
// setup_payment_method_order creates the Razorpay order; the customer authorises
// it in the hosted Checkout sheet; confirm_payment_method_order verifies the
// signature server-side and activates the mandate (#08). The mandate ceiling is
// the team's trust-tier cap — the backend owns that, the UI just runs the sheet.
//
// Stripe card capture (SetupIntent + Stripe Elements) is a separate flow; this
// composable covers the Razorpay/INR recurring path the demo bench uses.

import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { openRazorpayCheckout } from '@/utils/gateway'
import { successToast, errorToast } from '@/utils/toast'

export function useAddPaymentMethod({ onDone } = {}) {
  const { currentTeam } = useTeam()
  const setup = useCall({ url: m(API.setupPaymentMethodOrder), method: 'POST', immediate: false })
  const confirm = useCall({ url: m(API.confirmPaymentMethodOrder), method: 'POST', immediate: false })

  async function run(methodType, contact) {
    try {
      const params = { team: currentTeam.value, method_type: methodType }
      // A Razorpay card mandate needs a customer contact; the dialog collects it
      // inline when the billing profile has no phone.
      if (contact) params.contact = contact
      const order = await setup.submit(params)
      const handles = await openRazorpayCheckout(order, {
        name: 'Central',
        description: methodType === 'Card' ? 'Save card' : 'Set up UPI Autopay',
      })
      const res = await confirm.submit({
        payment_method: order.payment_method,
        ...handles,
      })
      successToast(`${methodType} added.`)
      onDone?.(res)
      return res
    } catch (e) {
      if (e?.message === 'cancelled') return
      errorToast(e, `Could not add ${methodType}.`)
    }
  }

  return { run, loading: computed(() => setup.loading || confirm.loading) }
}
