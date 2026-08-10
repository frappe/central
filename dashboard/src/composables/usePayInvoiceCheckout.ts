// Pay an Open invoice ON-SESSION via the gateway's hosted checkout
// (collection_mode = manual_checkout). Ported from the legacy dashboard.
//
// On-session carries no ₹15k silent-debit limit, so any amount is payable
// (ADR 0005, #50). Webhook-truth still holds: the backend stamps the attempt on
// confirm but the invoice flips to Paid only when the capture webhook lands — so
// we toast "received, confirming" not "paid".

import { useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import { openRazorpayCheckout, type RazorpayOrder } from '@/lib/gateway'
import { errorToast, infoToast, successToast } from '@/lib/toast'

export function usePayInvoiceCheckout({
	onDone,
}: {
	onDone?: (res: unknown) => void
} = {}) {
	const create = useCall<RazorpayOrder, { invoice: string }>({
		url: method(API.payInvoiceCheckout),
		method: 'POST',
		immediate: false,
	})
	const confirm = useCall<unknown, Record<string, unknown>>({
		url: method(API.confirmInvoiceCheckout),
		method: 'POST',
		immediate: false,
	})

	async function run(invoice: string): Promise<unknown> {
		try {
			await create.submit({ invoice })
			const order = create.data
			if (!order || order.created === false) {
				infoToast('No payment was started')
				return order
			}
			const handles = await openRazorpayCheckout(order, {
				name: 'Central',
				description: `Invoice ${invoice}`,
			})
			await confirm.submit({
				attempt: order.attempt,
				razorpay_order_id: handles.razorpay_order_id,
				razorpay_payment_id: handles.razorpay_payment_id,
				razorpay_signature: handles.razorpay_signature,
			})
			const res = confirm.data
			successToast(
				'Payment received — the invoice updates once the gateway confirms.',
			)
			onDone?.(res)
			return res
		} catch (e) {
			if ((e as Error)?.message === 'cancelled') return
			errorToast(e, 'Could not complete the payment')
		}
	}

	return { run, loading: computed(() => create.loading || confirm.loading) }
}
