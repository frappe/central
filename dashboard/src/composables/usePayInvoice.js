// Pay an outstanding (Open) invoice — postpaid one-off settlement.
//
// Webhook-truth: pay_invoice never returns Paid. It starts (or finds) a single
// in-flight Payment Attempt and returns {charged, reason?, attempt?}. We show an
// "initiated" toast and let the caller refetch; the invoice flips to Paid only
// when the gateway webhook lands. So this composable never asserts success —
// it asserts "we kicked off a charge".

import { useCall } from 'frappe-ui'
import { API, m } from '@/api/endpoints'
import { successToast, infoToast, errorToast } from '@/utils/toast'

export function usePayInvoice({ onDone } = {}) {
  const pay = useCall({
    url: m(API.payInvoice),
    immediate: false,
    onError: (e) => errorToast(e, 'Could not start the payment.'),
  })

  async function run(invoice) {
    const res = await pay.submit({ invoice })
    if (res?.charged === false) {
      // Already settling, nothing due, or not open — say so, don't double-charge.
      const reasons = {
        attempt_in_flight: 'A payment for this invoice is already in progress.',
        nothing_due: 'This invoice has nothing left to pay.',
        not_open: 'This invoice is no longer open.',
      }
      infoToast(reasons[res.reason] || 'No payment was started.')
    } else if (res) {
      successToast('Payment initiated — the invoice updates once the gateway confirms.')
    }
    onDone?.(res)
    return res
  }

  return { run, loading: pay.loading }
}
