// Wallet top-up — prepaid customers add credit through a real gateway order.
//
// Flow (webhook/confirm-truth, no magic crediting):
//   1. create_topup_order  → a real gateway order/checkout-session handle.
//   2. open the gateway's hosted element (Razorpay sheet) or redirect (Stripe).
//   3. confirm_topup       → backend verifies the gateway actually took the money,
//      then credits the wallet in the team's own currency.
// Stripe redirects out and returns to /billing/credits, which finishes step 3 from
// the URL — so for Stripe this composable ends at the redirect.

import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { openRazorpayCheckout, redirectToStripeCheckout } from '@/utils/gateway'
import { successToast, infoToast, errorToast } from '@/utils/toast'

export function useTopup({ onDone } = {}) {
  const { currentTeam } = useTeam()
  const createOrder = useCall({ url: m(API.createTopupOrder), immediate: false })
  const confirm = useCall({ url: m(API.confirmTopup), immediate: false })

  async function run(amount) {
    try {
      const order = await createOrder.submit({ team: currentTeam.value, amount })

      if (order.adapter_key === 'Stripe') {
        // Hands off to hosted Checkout; /billing/credits confirms on return.
        infoToast('Redirecting to secure checkout…')
        redirectToStripeCheckout(order)
        return
      }

      // Razorpay: collect the payment in the hosted sheet, then verify server-side.
      const handles = await openRazorpayCheckout(order, {
        name: 'Central',
        description: 'Wallet top-up',
      })
      const res = await confirm.submit({
        team: currentTeam.value,
        amount: order.amount,
        gateway: order.gateway,
        ...handles,
      })
      successToast('Wallet topped up.')
      onDone?.(res)
      return res
    } catch (e) {
      if (e?.message === 'cancelled') return // customer closed the sheet
      errorToast(e, 'Top-up could not be completed.')
    }
  }

  return {
    run,
    // Either leg in flight counts as busy.
    loading: computed(() => createOrder.loading || confirm.loading),
  }
}
