import type { AssetRow } from '@/composables/useServers'

// ── Money ──────────────────────────────────────────────────────────────────
// Display-only. Billing stores integer minor units (ADR 0003), but the dashboard
// endpoints already serialize MAJOR-unit numbers plus a `currency`, so the UI
// only formats what the backend returns — it never does money math.

const CURRENCY_SYMBOL: Record<string, string> = { INR: '₹', USD: '$' }

export function currencySymbol(currency: string): string {
  return CURRENCY_SYMBOL[currency] ?? ''
}

/** "₹5,000.00" — symbol + two-decimal grouped major units.
 *  Pass `trimTrailingZeros` to drop the decimals for whole amounts, e.g. plan
 *  prices ("₹4,000" instead of "₹4,000.00"). */
export function money(
  amount: number | null | undefined,
  currency = 'INR',
  { trimTrailingZeros = false }: { trimTrailingZeros?: boolean } = {},
): string {
  const value = Number(amount ?? 0)
  const decimals = trimTrailingZeros && Number.isInteger(value) ? 0 : 2
  const major = value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
  return `${currencySymbol(currency)}${major}`
}

/** Signed amount for ledgers: "+ ₹5,000.00" / "− ₹5,003.20". */
export function signedMoney(
  amount: number | null | undefined,
  currency = 'INR',
  isCredit = true,
): string {
  const sign = isCredit ? '+' : '−'
  return `${sign} ${money(Math.abs(Number(amount ?? 0)), currency)}`
}

/** Compact spec summary for a server row, e.g. "2 vCPU · 4 GB RAM · 40 GB".
 *  Skips parts the mirror hasn't reported yet. */
export function formatSpecs(server: AssetRow): string {
  const parts: string[] = []
  if (server.vcpus) parts.push(`${server.vcpus} vCPU`)
  if (server.memory_megabytes) parts.push(`${formatMemory(server.memory_megabytes)} RAM`)
  if (server.disk_gigabytes) parts.push(`${server.disk_gigabytes} GB`)
  return parts.join(' · ') || '—'
}

/** MB → human GB/MB. The doctype stores memory in megabytes. */
export function formatMemory(megabytes: number): string {
  if (megabytes >= 1024) {
    const gb = megabytes / 1024
    return `${Number.isInteger(gb) ? gb : gb.toFixed(1)} GB`
  }
  return `${megabytes} MB`
}

/** ISO datetime → short relative-ish label. Returns '' when unset. */
export function formatSyncedAt(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value.replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** ISO date (no time) → short label, e.g. "Jul 7, 2026". Returns '' when unset. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value.replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}
