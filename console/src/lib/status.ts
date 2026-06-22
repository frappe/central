import type { ServerStatus } from '@/types'

type BadgeTheme = 'green' | 'gray' | 'orange' | 'red' | 'blue'

// Asset status → Badge theme. Mirrors the Atlas lifecycle: Running is healthy,
// transient states are amber, terminal/failure states are red, the rest neutral.
// Keyed by string (not the ServerStatus union) since Atlas can report statuses
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

export function statusTheme(status: ServerStatus): BadgeTheme {
  return STATUS_THEME[status] ?? 'gray'
}

/** States a stopped server can be powered on from (mirrors central/api/servers.py). */
export const POWER_ON_STATES: ServerStatus[] = ['Stopped', 'Paused', 'Failed']

export function canStart(status: ServerStatus): boolean {
  return POWER_ON_STATES.includes(status)
}

export function canStop(status: ServerStatus): boolean {
  return status === 'Running'
}

export function isTerminated(status: ServerStatus): boolean {
  return status === 'Terminated'
}
