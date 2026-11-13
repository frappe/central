import type { BillingProfile } from '@/types/billing'

/**
 * The IGST rate a team's bills carry because its state is missing, or null when there is
 * nothing to tell it. A profile still loaded for another team is ignored.
 */
export function getMissingStateIgstRate(
	profile: BillingProfile | null | undefined,
	team: string | null,
): number | null {
	if (!profile || profile.team !== team) return null
	if (!profile.complete || !profile.gst_state_missing) return null
	return profile.igst_rate || null
}
