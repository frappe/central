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
export async function openRazorpayCheckout(order, { name = 'Central', description = '' } = {}) {
  await loadScript('https://checkout.razorpay.com/v1/checkout.js')
  return new Promise((resolve, reject) => {
    const rzp = new window.Razorpay({
      key: order.key || order.razorpay_key,
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
    })
    rzp.open()
  })
}

// Stripe hosted Checkout — a redirect; the page returns to /billing/credits,
// which finishes via confirm_topup using the session id in the URL.
export function redirectToStripeCheckout(order) {
  const url = order.checkout_url || order.url
  if (!url) throw new Error('No Stripe checkout URL returned')
  window.location.assign(url)
}
