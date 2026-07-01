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
  Paused: 'orange',
  Stopped: 'gray',
  Failed: 'red',
  Terminated: 'red',
}

export function statusTheme(status: AssetStatus): BadgeTheme {
  return STATUS_THEME[status] ?? 'gray'
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
