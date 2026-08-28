import type { InvitationStatus } from '@/types/api'
import type { PaymentAttempt } from '@/types/billing'
import type { Asset } from '@/types/Central/Asset'

// The DocType statuses plus Central's own derived display state (see displayStatus).
export type AssetStatus = NonNullable<Asset['status']> | 'Resizing'

export type BadgeTheme = 'green' | 'gray' | 'amber' | 'red' | 'blue' | 'violet'

// A server mid-resize reads as "Resizing" regardless of the raw Atlas status (which
// flips Running→Stopped→Running under it as the host power-cycles the VM). The flag is
// Central's own, set for the length of the background reshape job (#84).
export function isResizing(server: { resize_in_progress?: 0 | 1 }): boolean {
	return server.resize_in_progress === 1
}

/** The status to show for a row: a live action's transitional label ("Terminating"…)
 *  takes precedence, then "Resizing" while a reshape job runs, else the mirror status. */
export function displayStatus(server: {
	status?: AssetStatus
	resize_in_progress?: 0 | 1
	pending_action?: string | null
}): string {
	if (server.pending_action) return server.pending_action
	return isResizing(server) ? 'Resizing' : (server.status ?? 'Pending')
}

/** States a stopped server can be powered on from (mirrors central/api/servers.py). */
export const POWER_ON_STATES: AssetStatus[] = ['Stopped', 'Paused', 'Failed']

export function canStart(status?: AssetStatus): boolean {
	return status !== undefined && POWER_ON_STATES.includes(status)
}

export function canStop(status?: AssetStatus): boolean {
	return status === 'Running'
}

export function isTerminated(status?: AssetStatus): boolean {
	return status === 'Terminated'
}

/** Atlas is still provisioning the VM — power/open/terminate aren't available yet. */
const SETTING_UP_STATES: AssetStatus[] = [
	'Pending',
	'Provisioning',
	'Deploying',
]

export function isSettingUp(status?: AssetStatus): boolean {
	return status === undefined || SETTING_UP_STATES.includes(status)
}

// Team Invitation status → Badge theme. Pending is in-flight (amber), Accepted is
// done (green), everything else is inactive/neutral or a hard stop.
const INVITATION_STATUS_THEME: Record<InvitationStatus, BadgeTheme> = {
	Pending: 'amber',
	Accepted: 'green',
	Expired: 'gray',
	Revoked: 'red',
	Declined: 'gray',
}

export function invitationStatusTheme(status: InvitationStatus): BadgeTheme {
	return INVITATION_STATUS_THEME[status] ?? 'gray'
}

// Invoice status → Badge theme (case-insensitive), keyed by the Invoice DocType's
// status options. Paid is the normal state and stays gray — color is reserved
// for states that need attention.
const INVOICE_THEME: Record<string, BadgeTheme> = {
	paid: 'gray',
	open: 'amber',
	overdue: 'red',
	draft: 'gray',
	waived: 'gray',
	cancelled: 'gray',
}

export function invoiceTheme(status: string | null | undefined): BadgeTheme {
	return INVOICE_THEME[String(status ?? '').toLowerCase()] ?? 'gray'
}

// Subscription account_standing → Badge theme. Current is the normal state and
// stays gray; Past Due/Suspended need attention (amber) — matches PayingForRow's
// inline `statusInfo` check for the same field.
const STANDING_THEME: Record<string, BadgeTheme> = {
	current: 'gray',
	'past due': 'amber',
	suspended: 'amber',
}

export function standingTheme(standing: string | null | undefined): BadgeTheme {
	return STANDING_THEME[String(standing ?? '').toLowerCase()] ?? 'gray'
}

// Payment Attempt status → what a customer calls it, and its Badge theme. Same
// doctrine as invoices: the ordinary outcome is grey and colour is spent only on
// the states worth noticing — in-flight (nobody knows yet) and failed.
const ATTEMPT_DISPLAY: Record<string, { label: string; theme: BadgeTheme }> = {
	captured: { label: 'Paid', theme: 'gray' },
	authorised: { label: 'Authorised', theme: 'amber' },
	initiated: { label: 'Processing', theme: 'amber' },
	failed: { label: 'Failed', theme: 'red' },
	refunded: { label: 'Refunded', theme: 'gray' },
}

export function paymentAttemptDisplay(status: string | null | undefined): {
	label: string
	theme: BadgeTheme
} {
	const key = String(status ?? '').toLowerCase()
	return (
		ATTEMPT_DISPLAY[key] ?? {
			label: String(status ?? 'Unknown'),
			theme: 'gray',
		}
	)
}

export interface AttemptStory {
	/** Newest successful capture. */
	captured: PaymentAttempt | null
	/** Newest attempt still with the gateway (Initiated/Authorised). */
	inFlight: PaymentAttempt | null
	/** Newest refunded attempt. */
	refunded: PaymentAttempt | null
	failed: number
	/** Dunning retries that preceded the capture (all failures when uncaptured). */
	failedBeforeCapture: number
}

export function attemptStory(attempts: PaymentAttempt[]): AttemptStory {
	const sorted = [...attempts].sort((a, b) => b.at.localeCompare(a.at))
	const captured = sorted.find((a) => a.status === 'Captured') ?? null
	const inFlight =
		sorted.find((a) => a.status === 'Initiated' || a.status === 'Authorised') ??
		null
	const refunded = sorted.find((a) => a.status === 'Refunded') ?? null
	const failures = sorted.filter((a) => a.status === 'Failed')
	const failedBeforeCapture = captured
		? failures.filter((a) => a.at.localeCompare(captured.at) < 0).length
		: failures.length
	return {
		captured,
		inFlight,
		refunded,
		failed: failures.length,
		failedBeforeCapture,
	}
}
