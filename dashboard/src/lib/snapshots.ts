import dayjs from 'dayjs'
import { money } from '@/lib/format'
import type { BadgeTheme } from '@/lib/status'
import type {
	SnapshotStatus,
	SnapshotType,
	VMSnapshotRow,
} from '@/types/snapshots'

export const SNAPSHOT_TYPE_LABEL: Record<SnapshotType, string> = {
	Automatic: 'Daily',
	Manual: 'Manual',
	Terminate: 'Final',
}

export const SNAPSHOT_STATUS_THEME: Record<SnapshotStatus, BadgeTheme> = {
	Pending: 'amber',
	Available: 'green',
	Failed: 'red',
}

function hoursUntil(value: string): number {
	return Math.max(0, Math.ceil(dayjs(value).diff(dayjs(), 'hour', true)))
}

/** What a snapshot costs now, in the words a customer reads: free, or per month. */
export function snapshotCostLabel(
	row: VMSnapshotRow,
	currency: string,
): string {
	if (row.is_free && row.expires_at)
		return `Free · deleted in ${hoursUntil(row.expires_at)} h`
	if (row.is_free) return 'Free'
	if (row.monthly_cost == null) return 'Price not set'
	return `${money(row.monthly_cost, currency, { trimTrailingZeros: true })} / mo`
}

/** The monthly price of `gib` GB at `rate`, or null when the region has no price. */
export function snapshotMonthlyCost(
	gib: number,
	rate: number | null,
	currency: string,
): string | null {
	if (rate == null) return null
	return `${money(gib * rate, currency, { trimTrailingZeros: true })} / mo`
}
