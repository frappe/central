import type { Asset } from '@/types/Central/Asset'
import type { InvitationStatus } from '@/types/api'

export type AssetStatus = NonNullable<Asset['status']> | 'Provisioning' | (string & {})

type BadgeTheme = 'green' | 'gray' | 'orange' | 'red' | 'blue' | 'violet'

// Asset status → Badge theme. Mirrors the Atlas lifecycle: Running is healthy,
// transient states are amber, terminal/failure states are red, the rest neutral.
// Keyed by string (not the AssetStatus union) since Atlas can report statuses
// beyond the known set — anything unmapped falls back to neutral gray.
const STATUS_THEME: Record<string, BadgeTheme> = {
  Running: 'green',
  Pending: 'orange',
  Provisioning: 'orange',
  Resizing: 'orange',
  Paused: 'orange',
  Stopped: 'gray',
  Failed: 'red',
  Terminated: 'red',
}

export function statusTheme(status: AssetStatus): BadgeTheme {
  return STATUS_THEME[status] ?? 'gray'
}

// A server mid-resize reads as "Resizing" regardless of the raw Atlas status (which
// flips Running→Stopped→Running under it as the host power-cycles the VM). The flag is
// Central's own, set for the length of the background reshape job (#84).
export function isResizing(server: { resize_in_progress?: 0 | 1 }): boolean {
  return server.resize_in_progress === 1
}

/** The status to show for a row: "Resizing" while a reshape job runs, else the mirror. */
export function displayStatus(server: { status?: AssetStatus; resize_in_progress?: 0 | 1 }): AssetStatus {
  return isResizing(server) ? 'Resizing' : (server.status ?? 'Pending')
}

/** States a stopped server can be powered on from (mirrors central/api/servers.py). */
export const POWER_ON_STATES: AssetStatus[] = ['Stopped', 'Paused', 'Failed']

export function canStart(status: AssetStatus): boolean {
  return POWER_ON_STATES.includes(status)
}

export function canStop(status: AssetStatus): boolean {
  return status === 'Running'
}

export function isTerminated(status: AssetStatus): boolean {
  return status === 'Terminated'
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

// Subscription / invoice account-standing → Badge theme. Current is healthy,
// past_due/dunning amber, suspended/terminated red.
const STANDING_THEME: Record<string, BadgeTheme> = {
  Current: 'green',
  Active: 'green',
  Paid: 'green',
  Trialing: 'blue',
  past_due: 'orange',
  Past_Due: 'orange',
  Overdue: 'orange',
  Unpaid: 'orange',
  Dunning: 'orange',
  suspended: 'red',
  Suspended: 'red',
  Terminated: 'red',
  Void: 'gray',
}

export function standingTheme(standing: string | null | undefined): BadgeTheme {
  return (standing ? STANDING_THEME[standing] : undefined) ?? 'gray'
}

// Invoice status → Badge theme (case-insensitive): Paid green, Open/Unpaid amber,
// Overdue red, Void/Draft neutral.
const INVOICE_THEME: Record<string, BadgeTheme> = {
  paid: 'green',
  open: 'orange',
  unpaid: 'orange',
  overdue: 'red',
  void: 'gray',
  draft: 'gray',
}

export function invoiceTheme(status: string | null | undefined): BadgeTheme {
  return INVOICE_THEME[String(status ?? '').toLowerCase()] ?? 'gray'
}
