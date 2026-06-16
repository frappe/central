// Hand a started order to the gateway's hosted element, resolve when the customer
// finishes. Raw card/UPI data never touches our form — the gateway collects it.
//
// The backend's create_topup_order / initiate_card_setup return an adapter_key
// plus gateway handles; this opens the matching sheet. Webhook-truth still
// applies: the caller confirms server-side after this resolves.

function loadScript(src) {
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
  order,
  { name = 'Central', description = '', displayPayPal = false } = {},
) {
  await loadScript('https://checkout.razorpay.com/v1/checkout.js')
  return new Promise((resolve, reject) => {
    const options = {
      // Backend (create_order / setup_payment_method) returns the publishable
      // key id as `key_id`; keep the older aliases as fallbacks.
      key: order.key_id || order.key || order.razorpay_key,
      order_id: order.order_id || order.razorpay_order_id || order.id,
      amount: order.amount_in_subunits || undefined,
      currency: order.currency,
      name,
      description,
      handler: (resp) =>
        resolve({
          razorpay_order_id: resp.razorpay_order_id,
          razorpay_payment_id: resp.razorpay_payment_id,
          razorpay_signature: resp.razorpay_signature,
          // Present for recurring (UPI Autopay / card mandate) setups.
          razorpay_token_id: resp.razorpay_token_id,
        }),
      modal: { ondismiss: () => reject(new Error('cancelled')) },
    }
    // Associate the payment with the team's reused customer (also lets top-ups
    // prefill it), and for a mandate setup run Checkout in recurring mode — the
    // only way Razorpay issues the token the confirm step authorises.
    if (order.customer_id) options.customer_id = order.customer_id
    if (order.recurring) options.recurring = 1
    // Show only the PayPal block when this is a Via-Razorpay PayPal top-up, so the
    // sheet opens straight on PayPal rather than the full method menu.
    if (displayPayPal) {
      options.config = {
        display: {
          blocks: {
            paypal: { name: 'Pay with PayPal', instruments: [{ method: 'paypal' }] },
          },
          sequence: ['block.paypal'],
          preferences: { show_default_blocks: false },
        },
      }
    }
    const rzp = new window.Razorpay(options)
    rzp.open()
  })
}

// PayPal Buttons — PayPal is a directly-settled gateway (ADR 0007), so it runs its
// own approval flow (Buttons + a PayPal-hosted popup), not the Razorpay sheet. We
// render the buttons against the order create_topup_order already created; on
// approval the caller captures it server-side (confirm_topup) for webhook-truth.
export async function mountPayPalButtons(el, order, { onApprove, onError } = {}) {
  if (!order?.client_id) throw new Error('PayPal client id missing.')
  // PayPal's SDK is keyed by client id + currency; load it once per pair.
  await loadScript(
    `https://www.paypal.com/sdk/js?client-id=${encodeURIComponent(order.client_id)}` +
      `&currency=${encodeURIComponent(order.currency)}&intent=capture`,
  )
  if (!window.paypal) throw new Error('PayPal SDK failed to load.')
  return window.paypal
    .Buttons({
      // The order is already created server-side; hand its id to the buttons.
      createOrder: () => order.order_id,
      onApprove: (data) => onApprove?.(data.orderID || order.order_id),
      onError: (e) => onError?.(e),
    })
    .render(el)
}
