import type { InvitationStatus } from '@/types/api'
import type { Asset } from '@/types/Central/Asset'

// The DocType statuses plus Central's own derived display state (see displayStatus).
export type AssetStatus = NonNullable<Asset['status']> | 'Resizing'

export type BadgeTheme = 'green' | 'gray' | 'orange' | 'red' | 'blue' | 'violet'

// A server mid-resize reads as "Resizing" regardless of the raw Atlas status (which
// flips Running→Stopped→Running under it as the host power-cycles the VM). The flag is
// Central's own, set for the length of the background reshape job (#84).
export function isResizing(server: { resize_in_progress?: 0 | 1 }): boolean {
	return server.resize_in_progress === 1
}

/** The status to show for a row: "Resizing" while a reshape job runs, else the mirror. */
export function displayStatus(server: {
	status?: AssetStatus
	resize_in_progress?: 0 | 1
}): AssetStatus {
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
	Pending: 'orange',
	Accepted: 'green',
	Expired: 'gray',
	Revoked: 'red',
	Declined: 'gray',
}

export function invitationStatusTheme(status: InvitationStatus): BadgeTheme {
	return INVITATION_STATUS_THEME[status] ?? 'gray'
}

// Invoice status → Badge theme (case-insensitive), keyed by the Invoice DocType's
// status options: Paid green, Open amber, Overdue red, Draft/Waived/Cancelled neutral.
const INVOICE_THEME: Record<string, BadgeTheme> = {
	paid: 'green',
	open: 'orange',
	overdue: 'red',
	draft: 'gray',
	waived: 'gray',
	cancelled: 'gray',
}

export function invoiceTheme(status: string | null | undefined): BadgeTheme {
	return INVOICE_THEME[String(status ?? '').toLowerCase()] ?? 'gray'
}
