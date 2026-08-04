// Pay an outstanding (Open) invoice — postpaid one-off settlement.
// Ported from the legacy dashboard.
//
// Webhook-truth: pay_invoice never returns Paid. It starts (or finds) a single
// in-flight Payment Attempt and returns {charged, reason?, attempt?}. We show an
// "initiated" toast and let the caller refetch; the invoice flips to Paid only
// when the gateway webhook lands. So this composable never asserts success — it
// asserts "we kicked off a charge".

import { useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import { errorToast, infoToast, successToast } from '@/lib/toast'

interface PayResult {
	charged?: boolean
	reason?: string
	attempt?: string
}

export function usePayInvoice({
	onDone,
}: {
	onDone?: (res: PayResult | undefined) => void
} = {}) {
	const pay = useCall<PayResult, { invoice: string }>({
		url: method(API.payInvoice),
		method: 'POST',
		immediate: false,
		onError: (e: unknown) => errorToast(e, 'Could not start the payment.'),
	})

	async function run(invoice: string): Promise<PayResult | undefined> {
		await pay.submit({ invoice })
		const res = pay.data ?? undefined
		if (res?.charged === false) {
			// Already settling, nothing due, or not open — say so, don't double-charge.
			const reasons: Record<string, string> = {
				attempt_in_flight: 'A payment for this invoice is already in progress.',
				nothing_due: 'This invoice has nothing left to pay.',
				not_open: 'This invoice is no longer open.',
			}
			infoToast(
				(res.reason && reasons[res.reason]) || 'No payment was started.',
			)
		} else if (res) {
			successToast(
				'Payment initiated — the invoice updates once the gateway confirms.',
			)
		}
		onDone?.(res)
		return res
	}

	// Wrap in a computed so the reactive `loading` survives being returned out of
	// the reactive useCall object (reading it raw would snapshot a boolean).
	return { run, loading: computed(() => pay.loading) }
}
