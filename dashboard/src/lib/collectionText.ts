import { money } from '@/lib/format'
import { __ } from '@/lib/translate'
import type { CollectionStatus } from '@/types/billing'

/** What adding a card costs, shown before the customer adds one. */
export const cardCheckText = __(
	'We check a card with a small charge (₹0.50 or $0.50) and refund it. Indian cards set up for auto-pay and UPI are not charged.',
)

/** An amount with the tax note it includes, e.g. "₹15,000 (incl. IGST 18%)". */
export function withNote(amount: string, note?: string | null): string {
	// A format, not text: the note is already translated.
	return note ? `${amount} (${note})` : amount
}

/** The most the card or UPI may pay automatically, with the tax that amount includes. */
export function limitText(status: CollectionStatus, limit: number): string {
	return withNote(money(limit, status.currency), status.limit_tax_note)
}
