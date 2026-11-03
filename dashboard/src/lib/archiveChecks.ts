import type {
	ArchiveCheck,
	ArchiveCheckKey,
} from '@/composables/useTeamArchiveChecks'
import { plural } from '@/lib/format'

interface CheckCopy {
	passed: string
	failed: (count: number) => string
	action: string
	route?: string
}

export const CHECK_COPY: Record<ArchiveCheckKey, CheckCopy> = {
	servers: {
		passed: 'All servers are terminated',
		failed: (count) => `${plural(count, 'server')} not terminated`,
		action: 'Open servers',
		route: '/servers',
	},
	snapshots: {
		passed: 'No paid snapshots',
		failed: (count) => `${plural(count, 'paid snapshot')} to delete`,
		action: 'Open snapshots',
		route: '/servers/snapshots',
	},
	buckets: {
		passed: 'No buckets',
		failed: (count) => `${plural(count, 'bucket subscription')} still billing`,
		action: 'Open storage',
		route: '/object-storage',
	},
	add_ons: {
		passed: 'No other paid add-ons',
		failed: (count) => `${plural(count, 'other paid add-on')} still billing`,
		action: 'Open billing',
		route: '/billing',
	},
	invoices: {
		passed: 'No unpaid invoices',
		failed: (count) => plural(count, 'unpaid invoice'),
		action: 'Pay invoices',
		route: '/billing/invoices',
	},
	members: {
		passed: 'No other members',
		failed: (count) => plural(count, 'other member'),
		action: 'Transfer ownership',
		route: '/team/members',
	},
	final_bill: {
		passed: "This month's charges can be collected",
		failed: () => "This month's charges need a payment method",
		action: 'Add a card',
		route: '/billing',
	},
	suspended: {
		passed: 'Team is active',
		failed: () => 'Team is suspended',
		action: 'Contact support',
	},
}

export function describeCheck(check: ArchiveCheck): string {
	const copy = CHECK_COPY[check.key]
	return check.passed ? copy.passed : copy.failed(check.count)
}
