// Add a card on the Stripe rail (SetupIntent + Stripe Elements). Counterpart to
// the Razorpay path in useAddPaymentMethod. Ported from the legacy dashboard.
//
// The PAN is entered in a Stripe Element — a PCI-scoped iframe Stripe hosts; it
// never touches our form or server. Flow (#08):
//   1. initiate_card_setup → an off-session SetupIntent (client_secret) + a
//      pending Payment Method doc.
//   2. confirmCardSetup with the card → Stripe attaches the method to the team's
//      customer and returns the pm_… handle.
//   3. confirm_card → backend runs the micro-charge validation and activates it.
//
// publishableKey + client_secret come from the backend; we never hardcode a key.

import { ref } from 'vue'
import {
	loadStripe,
	type Stripe,
	type StripeCardElement,
} from '@stripe/stripe-js'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { successToast, errorToast } from '@/lib/toast'

interface CardSetupOrder {
	client_secret?: string
	payment_method?: string
}

interface ConfirmCardResult {
	payment_method: string
	status: string
}

interface MountOptions {
	team: string
	publishableKey: string | null | undefined
}

export function useAddStripeCard({
	onDone,
}: {
	onDone?: (res: ConfirmCardResult) => void
} = {}) {
	const initiate = useCall<CardSetupOrder, { team: string }>({
		url: method(API.initiateCardSetup),
		method: 'POST',
		immediate: false,
	})
	const confirm = useCall<ConfirmCardResult, Record<string, unknown>>({
		url: method(API.confirmCard),
		method: 'POST',
		immediate: false,
	})
	const complete = ref(false) // the card field is filled in and valid
	const submitting = ref(false)

	let stripe: Stripe | null = null
	let card: StripeCardElement | null = null
	let orderPromise: Promise<CardSetupOrder | null> | null = null

	// Load Stripe.js and mount the card Element straight away. The SetupIntent (a
	// server→Stripe round-trip) is kicked off in parallel and awaited only at
	// submit — so the card field appears instantly instead of waiting on the
	// backend, by far the bigger source of perceived load time.
	async function mount(
		el: string | HTMLElement,
		{ team, publishableKey }: MountOptions,
	): Promise<void> {
		if (!publishableKey) throw new Error('Stripe publishable key missing.')
		stripe = await loadStripe(publishableKey)
		if (!stripe) throw new Error('Stripe.js failed to load.')

		// Swallow here so a reject doesn't become an unhandled rejection if the user
		// cancels before submitting; submit() turns the null into a clean message.
		// useCall.submit() resolves void — read the order off `.data` once it settles.
		orderPromise = initiate
			.submit({ team })
			.then(() => initiate.data)
			.catch(() => null)
		card = stripe.elements().create('card', { hidePostalCode: true })
		card.on('change', (e) => (complete.value = !!e.complete))
		card.mount(el)
	}

	// Confirm the SetupIntent with the entered card, then activate it server-side.
	async function submit(): Promise<ConfirmCardResult | undefined> {
		if (!stripe || !card || !orderPromise) return
		submitting.value = true
		try {
			const order = await orderPromise // usually already resolved by now
			if (!order?.client_secret)
				throw new Error('Could not start card setup. Please try again.')

			const { paymentMethod, error: pmError } =
				await stripe.createPaymentMethod({
					type: 'card',
					card,
				})
			if (pmError) throw pmError

			const { error: setupError } = await stripe.confirmCardSetup(
				order.client_secret,
				{
					payment_method: paymentMethod.id,
				},
			)
			if (setupError) throw setupError

			const c = paymentMethod.card
			await confirm.submit({
				payment_method: order.payment_method,
				gateway_method_id: paymentMethod.id,
				display_label: `${capitalise(c?.brand)} ····${c?.last4}`,
				expiry_month: c?.exp_month,
				expiry_year: c?.exp_year,
			})
			const res = confirm.data
			if (!res || res.status !== 'Active') {
				errorToast("We couldn't verify that card. Please try a different one.")
				return
			}
			successToast('Card added.')
			onDone?.(res)
			return res
		} catch (e) {
			errorToast(e, 'Could not add card.')
		} finally {
			submitting.value = false
		}
	}

	function destroy(): void {
		card?.destroy()
		card = null
		orderPromise = null
		complete.value = false
	}

	return { mount, submit, destroy, complete, submitting }
}

function capitalise(s: string | undefined): string {
	return s ? s.charAt(0).toUpperCase() + s.slice(1) : ''
}
