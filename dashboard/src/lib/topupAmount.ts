// The largest amount a link may prefill: a sanity bound, not a top-up limit.
export const MAX_PREFILL_AMOUNT = 10_000_000

/** A `?topup=` query value as a whole amount to prefill, or null when it is not one. */
export function parseTopupAmount(value: unknown): number | null {
	const raw = Array.isArray(value) ? value[0] : value
	if (typeof raw !== 'string' || !/^\d+(\.\d{1,2})?$/.test(raw)) return null
	const amount = Number(raw)
	if (amount < 1 || amount > MAX_PREFILL_AMOUNT) return null
	return amount
}
