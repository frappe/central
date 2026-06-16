// Pay an Open invoice ON-SESSION via the gateway's hosted checkout
// (collection_mode = manual_checkout). On-session carries no ₹15k silent-debit
// limit, so any amount is payable (ADR 0005, #50). Webhook-truth still holds: the
// backend stamps the attempt on confirm but the invoice flips to Paid only when
// the capture webhook lands — so we toast "received, confirming" not "paid".
import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, m } from '@/api/endpoints'
import { openRazorpayCheckout } from '@/utils/gateway'
import { successToast, infoToast, errorToast } from '@/utils/toast'

export function usePayInvoiceCheckout({ onDone } = {}) {
  const create = useCall({ url: m(API.payInvoiceCheckout), method: 'POST', immediate: false })
  const confirm = useCall({ url: m(API.confirmInvoiceCheckout), method: 'POST', immediate: false })

  async function run(invoice) {
    try {
      const order = await create.submit({ invoice })
      if (order?.created === false) {
        infoToast('No payment was started.')
        return order
      }
      const handles = await openRazorpayCheckout(order, {
        name: 'Central',
        description: `Invoice ${invoice}`,
      })
      const res = await confirm.submit({
        attempt: order.attempt,
        razorpay_order_id: handles.razorpay_order_id,
        razorpay_payment_id: handles.razorpay_payment_id,
        razorpay_signature: handles.razorpay_signature,
      })
      successToast('Payment received — the invoice updates once the gateway confirms.')
      onDone?.(res)
      return res
    } catch (e) {
      if (e?.message === 'cancelled') return
      errorToast(e, 'Could not complete the payment.')
    }
  }

  return { run, loading: computed(() => create.loading || confirm.loading) }
}
