import { money } from '@/lib/format'
import type { CollectionStatus } from '@/types/billing'

/** An amount with the tax note it includes, e.g. "₹15,000 (incl. IGST 18%)". */
export function withNote(amount: string, note?: string | null): string {
	// A format, not text: the note is already translated.
	return note ? `${amount} (${note})` : amount
}

/** The most the card or UPI may pay automatically, with the tax that amount includes. */
export function limitText(status: CollectionStatus, limit: number): string {
	return withNote(money(limit, status.currency), status.limit_tax_note)
}
