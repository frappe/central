import type { ServerStatus } from '@/types'

type BadgeTheme = 'green' | 'gray' | 'orange' | 'red' | 'blue'

// Asset status → Badge theme. Mirrors the Atlas lifecycle: Running is healthy,
// transient states are amber, terminal/failure states are red, the rest neutral.
const STATUS_THEME: Record<ServerStatus, BadgeTheme> = {
  Running: 'green',
  Pending: 'orange',
  Paused: 'orange',
  Stopped: 'gray',
  Failed: 'red',
  Terminated: 'red',
}

export function statusTheme(status: ServerStatus): BadgeTheme {
  return STATUS_THEME[status] ?? 'gray'
}

/** States a stopped server can be powered on from (mirrors central/atlas.py). */
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
