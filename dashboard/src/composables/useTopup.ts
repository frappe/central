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

import {
	loadStripe,
	type Stripe,
	type StripeCardElement,
} from '@stripe/stripe-js'
import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import {
	type GatewayOrder,
	mountPayPalButtons,
	openRazorpayCheckout,
} from '@/lib/gateway'
import { errorToast, successToast } from '@/lib/toast'

interface BeginResult {
	card?: boolean
	paypal?: boolean
}

export function useTopup({ onDone }: { onDone?: (res: unknown) => void } = {}) {
	const { activeTeam } = useSession()
	const createOrder = useCall<GatewayOrder, Record<string, unknown>>({
		url: method(API.createTopupOrder),
		method: 'POST',
		immediate: false,
	})
	const confirm = useCall<unknown, Record<string, unknown>>({
		url: method(API.confirmTopup),
		method: 'POST',
		immediate: false,
	})

	// Stripe card-phase state — populated only once a Stripe order needs a card.
	const cardComplete = ref(false)
	const submitting = ref(false)
	let stripe: Stripe | null = null
	let card: StripeCardElement | null = null
	let order: GatewayOrder | null = null
	let billingGroup: string | null = null

	// Create the gateway order, then resolve by rail:
	//  - Stripe → { card: true }: dialog mounts the card Element.
	//  - Paypal → { paypal: true }: dialog mounts PayPal Buttons (ADR 0007).
	//  - Razorpay → collected in its hosted sheet, the whole top-up resolves here.
	// `payMethod` is 'paypal' for an international PayPal top-up; `instrument` is the
	// recharge tile the customer chose (Card / RuPay card / UPI / Netbanking).
	async function begin(
		amount: number,
		payMethod?: string,
		onSheet?: () => void,
		instrument?: string,
		group?: string | null,
	): Promise<BeginResult> {
		try {
			billingGroup = group || null
			await createOrder.submit({
				team: activeTeam.value,
				amount,
				method: payMethod,
				// What the customer tapped. The backend resolves the rail from it, so a
				// card top-up reaches Stripe even though Razorpay owns the INR default.
				instrument,
				// Earmarks the credit to one Billing Group's own budget instead of the
				// general pool (ARCHITECTURE.md §2.1). Validated again in confirm_topup.
				billing_group: billingGroup,
			})
			if (createOrder.error) throw createOrder.error
			// Capture locally: the shared `order` is nulled by destroy() when the dialog
			// closes, which can race an in-flight confirm below.
			const o = createOrder.data
			if (!o) throw new Error('Could not start the top-up.')
			order = o
			if (o.adapter_key === 'Stripe') return { card: true }
			if (o.adapter_key === 'Paypal') return { paypal: true }

			// Razorpay collects in its own hosted sheet on <body>; a caller showing a
			// modal must drop it now so the sheet isn't stuck behind the overlay.
			onSheet?.()
			const handles = await openRazorpayCheckout(o, {
				name: 'Central',
				description: 'Wallet top-up',
				displayPayPal: o.display_paypal,
			})
			await settle({
				team: activeTeam.value,
				amount: o.amount,
				gateway: o.gateway,
				billing_group: billingGroup,
				...handles,
			})
		} catch (e) {
			if ((e as Error)?.message !== 'cancelled')
				errorToast(e, 'Top-up could not be completed')
		}
		return { card: false }
	}

	// Run confirm_topup and only declare success when the server actually credited
	// the wallet — submit() resolves even on a server error (it sets .error), so a
	// failed confirm must not toast a false "topped up".
	async function settle(params: Record<string, unknown>): Promise<void> {
		await confirm.submit(params)
		if (confirm.error) throw confirm.error
		finish(confirm.data)
	}

	// Render PayPal Buttons for the order begin() created. On approval we capture
	// the order server-side (confirm_topup) and credit what PayPal actually took.
	async function mountPayPal(el: Element): Promise<void> {
		const o = order
		if (o?.adapter_key !== 'Paypal') return
		await mountPayPalButtons(el, o, {
			onApprove: async (paypalOrderId: string) => {
				submitting.value = true
				try {
					await settle({
						team: activeTeam.value,
						amount: o.amount,
						gateway: o.gateway,
						billing_group: billingGroup,
						paypal_order_id: paypalOrderId,
					})
				} catch (e) {
					errorToast(e, 'Top-up could not be completed')
				} finally {
					submitting.value = false
				}
			},
			onError: (e) => errorToast(e, 'PayPal could not start'),
		})
	}

	// Mount the Stripe card Element for the order begin() created.
	async function mountCard(el: string | HTMLElement): Promise<void> {
		const o = order
		if (o?.adapter_key !== 'Stripe' || !o.publishable_key)
			throw new Error('Stripe publishable key missing.')
		stripe = await loadStripe(o.publishable_key)
		if (!stripe) throw new Error('Stripe.js failed to load.')
		card = stripe.elements().create('card', { hidePostalCode: true })
		card.on('change', (e) => (cardComplete.value = !!e.complete))
		card.mount(el)
	}

	// Confirm the PaymentIntent with the entered card, then credit server-side from
	// what Stripe actually charged.
	async function pay(): Promise<unknown> {
		const o = order
		if (!stripe || !card || o?.adapter_key !== 'Stripe' || !o.client_secret)
			return
		submitting.value = true
		try {
			const { paymentIntent, error } = await stripe.confirmCardPayment(
				o.client_secret,
				{
					payment_method: { card },
				},
			)
			if (error) throw error
			if (paymentIntent?.status !== 'succeeded')
				throw new Error('Payment was not completed.')

			await settle({
				team: activeTeam.value,
				amount: o.amount,
				gateway: o.gateway,
				billing_group: billingGroup,
				payment_intent: paymentIntent.id,
			})
			return confirm.data
		} catch (e) {
			errorToast(e, 'Top-up could not be completed')
		} finally {
			submitting.value = false
		}
	}

	function finish(res: unknown): void {
		successToast('Wallet topped up')
		onDone?.(res)
	}

	function destroy(): void {
		card?.destroy()
		card = null
		stripe = null
		order = null
		billingGroup = null
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
