// Add a recurring payment method on the Razorpay rail: a UPI Autopay mandate or a
// RuPay card token (ADR 0022).
// Ported from the legacy dashboard.
//
// setup_payment_method_order creates the Razorpay order; the customer authorises
// it in the hosted Checkout sheet; confirm_payment_method_order verifies the
// signature server-side and activates the mandate (#08). The mandate ceiling is
// the team's trust-tier cap — the backend owns that, the UI just runs the sheet.
//
// Stripe card capture (SetupIntent + Stripe Elements) is a separate flow
// (useAddStripeCard); this covers the Razorpay/INR recurring path.

import { useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { openRazorpayCheckout, type RazorpayOrder } from '@/lib/gateway'
import { errorToast, successToast } from '@/lib/toast'

interface MethodResult {
	payment_method: string
	status: string
}

export function useAddPaymentMethod({
	onDone,
}: {
	onDone?: (res?: MethodResult) => void
} = {}) {
	const { activeTeam } = useSession()
	const setup = useCall<RazorpayOrder, Record<string, unknown>>({
		url: method(API.setupPaymentMethodOrder),
		method: 'POST',
		immediate: false,
	})
	const confirm = useCall<MethodResult, Record<string, unknown>>({
		url: method(API.confirmPaymentMethodOrder),
		method: 'POST',
		immediate: false,
	})

	async function run(
		methodType: string,
		contact?: string,
		instrument?: string,
		afterDecline = false,
	): Promise<MethodResult | undefined> {
		try {
			const params: Record<string, unknown> = {
				team: activeTeam.value,
				method_type: methodType,
				// What the customer tapped. The backend resolves the rail from it, so a
				// RuPay card goes to Razorpay without anyone reading the card number.
				instrument: instrument || methodType,
				// Provenance: the customer arrived here from a card the other rail
				// refused. The server checks it against a real decline before recording
				// it, because the field feeds the gateway comparison.
				after_decline: afterDecline,
			}
			// A Razorpay card mandate needs a customer contact; the dialog collects it
			// inline when the billing profile has no phone.
			if (contact) params.contact = contact
			await setup.submit(params)
			// useCall stores the failure rather than throwing it, so rethrow it here.
			// Otherwise a generic message replaces the server's, and the customer is
			// told "something went wrong" when the server said exactly what was wrong.
			if (setup.error) throw setup.error
			const order = setup.data
			if (!order) throw new Error('Could not start the payment method setup.')
			const handles = await openRazorpayCheckout(order, {
				name: 'Central',
				description: methodType === 'Card' ? 'Save card' : 'Set up UPI Autopay',
			})
			await confirm.submit({ payment_method: order.payment_method, ...handles })
			const res = confirm.data ?? undefined
			successToast(`${methodType} added`)
			onDone?.(res)
			return res
		} catch (e) {
			if ((e as Error)?.message === 'cancelled') return
			errorToast(e, `Could not add ${methodType}`)
		}
	}

	return { run, loading: computed(() => setup.loading || confirm.loading) }
}
