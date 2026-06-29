import type { Asset } from '@/types/Central/Asset'

export type AssetStatus = NonNullable<Asset['status']> | 'Provisioning' | (string & {})

type BadgeTheme = 'green' | 'gray' | 'orange' | 'red' | 'blue'

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
