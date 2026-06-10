// Display-only money formatting.
//
// Internally billing stores integer minor units (ADR 0003), but the customer
// dashboard endpoints already serialize amounts as MAJOR-unit numbers plus a
// `currency` (see central.billing.api.dashboard). The UI never does money math —
// it formats what the backend returns.

const SYMBOL = { INR: '₹', EUR: '€', USD: '$' }

export function currencySymbol(currency) {
  return SYMBOL[currency] ?? ''
}

export function money(amount, currency = 'INR') {
  const n = Number(amount ?? 0)
  const major = n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  return `${currencySymbol(currency)}${major}`
}

// Signed amount for ledgers: "+ ₹5,000.00" / "− ₹5,003.20".
export function signedMoney(amount, currency = 'INR', isCredit = true) {
  const sign = isCredit ? '+' : '−'
  return `${sign} ${money(Math.abs(Number(amount ?? 0)), currency)}`
}
