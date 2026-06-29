// Add a recurring payment method (Razorpay path: UPI Autopay mandate or card token).
// Ported from the legacy dashboard.
//
// setup_payment_method_order creates the Razorpay order; the customer authorises
// it in the hosted Checkout sheet; confirm_payment_method_order verifies the
// signature server-side and activates the mandate (#08). The mandate ceiling is
// the team's trust-tier cap — the backend owns that, the UI just runs the sheet.
//
// Stripe card capture (SetupIntent + Stripe Elements) is a separate flow
// (useAddStripeCard); this covers the Razorpay/INR recurring path.

import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { openRazorpayCheckout, type GatewayOrder } from '@/lib/gateway'
import { successToast, errorToast } from '@/lib/toast'

interface MethodResult {
  payment_method: string
  status: string
}

export function useAddPaymentMethod({ onDone }: { onDone?: (res?: MethodResult) => void } = {}) {
  const { activeTeam } = useSession()
  const setup = useCall<GatewayOrder, Record<string, unknown>>({
    url: method(API.setupPaymentMethodOrder),
    immediate: false,
  })
  const confirm = useCall<MethodResult, Record<string, unknown>>({
    url: method(API.confirmPaymentMethodOrder),
    immediate: false,
  })

  async function run(methodType: string, contact?: string): Promise<MethodResult | undefined> {
    try {
      const params: Record<string, unknown> = { team: activeTeam.value, method_type: methodType }
      // A Razorpay card mandate needs a customer contact; the dialog collects it
      // inline when the billing profile has no phone.
      if (contact) params.contact = contact
      await setup.submit(params)
      const order = setup.data
      if (!order) throw new Error('Could not start the payment method setup.')
      const handles = await openRazorpayCheckout(order, {
        name: 'Central',
        description: methodType === 'Card' ? 'Save card' : 'Set up UPI Autopay',
      })
      await confirm.submit({ payment_method: order.payment_method, ...handles })
      const res = confirm.data ?? undefined
      successToast(`${methodType} added.`)
      onDone?.(res)
      return res
    } catch (e) {
      if ((e as Error)?.message === 'cancelled') return
      errorToast(e, `Could not add ${methodType}.`)
    }
  }

  return { run, loading: computed(() => setup.loading || confirm.loading) }
}
