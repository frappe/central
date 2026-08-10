// Hand a started order to the gateway's hosted element, resolve when the customer
// finishes. Raw card/UPI data never touches our form — the gateway collects it.
// Ported from the legacy dashboard's utils/gateway.js.
//
// The backend's create_topup_order / setup_payment_method_order return an
// adapter_key plus gateway handles; this opens the matching sheet. Webhook-truth
// still applies: the caller confirms server-side after this resolves.

// A gateway order/handle bundle the backend returns from create_topup_order,
// setup_payment_method_order, initiate_card_setup, or pay_invoice_checkout. The
// `adapter_key` discriminates the rail, so a consumer that narrows on it sees only
// that rail's handles — never a Stripe field on a Razorpay order.

/** Fields every rail's order carries (amount/currency + setup/settlement bookkeeping). */
interface GatewayOrderBase {
	gateway?: string
	amount?: number
	currency?: string
	display_paypal?: boolean
	payment_method?: string
	attempt?: string
	created?: boolean
}

/** Razorpay hosted-sheet order (Checkout). */
export interface RazorpayOrder extends GatewayOrderBase {
	adapter_key: 'Razorpay'
	key_id?: string
	key?: string
	razorpay_key?: string
	order_id?: string
	razorpay_order_id?: string
	id?: string
	amount_in_subunits?: number
	customer_id?: string
	recurring?: number
	prefill?: { name?: string; email?: string; contact?: string }
}

/** Stripe in-app card order (PaymentIntent + Elements). */
export interface StripeOrder extends GatewayOrderBase {
	adapter_key: 'Stripe'
	publishable_key?: string | null
	client_secret?: string
}

/** PayPal directly-settled order (Buttons, ADR 0007). */
export interface PaypalOrder extends GatewayOrderBase {
	adapter_key: 'Paypal'
	client_id?: string
	order_id?: string
}

export type GatewayOrder = RazorpayOrder | StripeOrder | PaypalOrder

/** Payment handles a hosted sheet returns, verified server-side on confirm. */
export interface RazorpayHandles {
	razorpay_order_id?: string
	razorpay_payment_id?: string
	razorpay_signature?: string
	/** Present for recurring (UPI Autopay / card mandate) setups. */
	razorpay_token_id?: string
}

interface RazorpayOptions {
	name?: string
	description?: string
	displayPayPal?: boolean
}

interface PayPalCallbacks {
	onApprove?: (paypalOrderId: string) => void
	onError?: (error: unknown) => void
}

declare global {
	interface Window {
		Razorpay: new (options: Record<string, unknown>) => { open: () => void }
		paypal?: {
			Buttons: (config: Record<string, unknown>) => {
				render: (el: Element) => unknown
			}
		}
	}
}

function loadScript(src: string): Promise<void> {
	return new Promise((resolve, reject) => {
		if (document.querySelector(`script[src="${src}"]`)) return resolve()
		const s = document.createElement('script')
		s.src = src
		s.onload = () => resolve()
		s.onerror = () => reject(new Error(`Failed to load ${src}`))
		document.head.appendChild(s)
	})
}

// Razorpay Checkout — resolves with the payment handles to verify server-side.
// `displayPayPal` surfaces PayPal inside the sheet (a Via-Razorpay PayPal top-up,
// ADR 0005): PayPal is collected as a method here and settles through Razorpay.
export async function openRazorpayCheckout(
	order: RazorpayOrder,
	{
		name = 'Central',
		description = '',
		displayPayPal = false,
	}: RazorpayOptions = {},
): Promise<RazorpayHandles> {
	await loadScript('https://checkout.razorpay.com/v1/checkout.js')
	return new Promise<RazorpayHandles>((resolve, reject) => {
		const options: Record<string, unknown> = {
			// Backend returns the publishable key id as `key_id`; keep older aliases.
			key: order.key_id || order.key || order.razorpay_key,
			order_id: order.order_id || order.razorpay_order_id || order.id,
			amount: order.amount_in_subunits || undefined,
			currency: order.currency,
			name,
			description,
			handler: (resp: RazorpayHandles) =>
				resolve({
					razorpay_order_id: resp.razorpay_order_id,
					razorpay_payment_id: resp.razorpay_payment_id,
					razorpay_signature: resp.razorpay_signature,
					razorpay_token_id: resp.razorpay_token_id,
				}),
			modal: { ondismiss: () => reject(new Error('cancelled')) },
		}
		// Reuse the team's customer (also prefills top-ups); a mandate setup runs
		// Checkout in recurring mode — the only way Razorpay issues the token confirm
		// authorises.
		if (order.customer_id) options.customer_id = order.customer_id
		if (order.recurring) options.recurring = 1
		// Pre-populate name/email/contact: Razorpay does not fill these from
		// customer_id in recurring mode, so without this the sheet re-asks for the
		// contact details we already hold on the billing profile.
		if (order.prefill) options.prefill = order.prefill
		// Show only the PayPal block for a Via-Razorpay PayPal top-up, so the sheet
		// opens straight on PayPal rather than the full method menu.
		if (displayPayPal) {
			options.config = {
				display: {
					blocks: {
						paypal: {
							name: 'Pay with PayPal',
							instruments: [{ method: 'paypal' }],
						},
					},
					sequence: ['block.paypal'],
					preferences: { show_default_blocks: false },
				},
			}
		}
		new window.Razorpay(options).open()
	})
}

// PayPal Buttons — PayPal is a directly-settled gateway (ADR 0007), so it runs its
// own approval flow (Buttons + a PayPal-hosted popup), not the Razorpay sheet. We
// render the buttons against the order create_topup_order already created; on
// approval the caller captures it server-side (confirm_topup) for webhook-truth.
export async function mountPayPalButtons(
	el: Element,
	order: PaypalOrder,
	{ onApprove, onError }: PayPalCallbacks = {},
): Promise<unknown> {
	if (!order?.client_id) throw new Error('PayPal client id missing.')
	// PayPal's SDK is keyed by client id + currency; load it once per pair.
	await loadScript(
		`https://www.paypal.com/sdk/js?client-id=${encodeURIComponent(order.client_id)}` +
			`&currency=${encodeURIComponent(order.currency ?? '')}&intent=capture`,
	)
	if (!window.paypal) throw new Error('PayPal SDK failed to load.')
	return window.paypal
		.Buttons({
			createOrder: () => order.order_id,
			onApprove: (data: { orderID?: string }) =>
				onApprove?.(data.orderID || order.order_id || ''),
			onError: (e: unknown) => onError?.(e),
		})
		.render(el)
}
