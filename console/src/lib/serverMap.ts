import { displayStatus, isResizing } from '@/lib/status'
import type { AssetRow } from '@/composables/useServers'
import type { Region } from '@/types/Region'

// Display mapping for the servers map: one place that turns an Asset's mirror
// status into what the map shows (label, badge, dot colour, pulse). Terminated
// assets never reach the map — useServerMapData filters them out.

type BadgeTheme = 'green' | 'gray' | 'orange' | 'red' | 'blue'

export interface ServerVisual {
  /** Stable key the status filter matches on. */
  key: 'active' | 'settingUp' | 'paused' | 'stopped' | 'broken' | 'resizing'
  label: string
  badgeTheme: BadgeTheme
  /** CSS variable for the status dot on pins and rows. */
  dot: string
  /** Failed servers pulse red on the map. */
  pulse: boolean
}

const VISUALS: Record<ServerVisual['key'], ServerVisual> = {
  active: { key: 'active', label: 'Active', badgeTheme: 'green', dot: 'var(--ink-green-7)', pulse: false },
  settingUp: { key: 'settingUp', label: 'Setting up', badgeTheme: 'orange', dot: 'var(--ink-amber-7)', pulse: false },
  paused: { key: 'paused', label: 'Paused', badgeTheme: 'gray', dot: 'var(--ink-gray-5)', pulse: false },
  stopped: { key: 'stopped', label: 'Stopped', badgeTheme: 'gray', dot: 'var(--ink-gray-5)', pulse: false },
  broken: { key: 'broken', label: 'Broken', badgeTheme: 'red', dot: 'var(--ink-red-7)', pulse: true },
  resizing: { key: 'resizing', label: 'Resizing', badgeTheme: 'orange', dot: 'var(--ink-amber-7)', pulse: false },
}

// Mirror status → visual. Keyed by string because Atlas can report statuses
// beyond the known set — anything unmapped reads as "Setting up" (transient).
const STATUS_VISUAL: Record<string, ServerVisual> = {
  Running: VISUALS.active,
  Pending: VISUALS.settingUp,
  Provisioning: VISUALS.settingUp,
  Paused: VISUALS.paused,
  Stopped: VISUALS.stopped,
  Failed: VISUALS.broken,
}

export function statusVisual(server: AssetRow): ServerVisual {
  if (isResizing(server)) return VISUALS.resizing
  return STATUS_VISUAL[displayStatus(server)] ?? VISUALS.settingUp
}

/** The status filter menu, in lifecycle order. */
export const STATUS_FILTERS: ServerVisual[] = [
  VISUALS.active,
  VISUALS.settingUp,
  VISUALS.resizing,
  VISUALS.paused,
  VISUALS.stopped,
  VISUALS.broken,
]

function formatMemory(megabytes: number): string {
  if (megabytes < 1024) return `${megabytes} MB`
  const gigabytes = megabytes / 1024
  return `${Number.isInteger(gigabytes) ? gigabytes : gigabytes.toFixed(1)} GB`
}

/** "4 vCPU, 8 GB RAM, 75 GB Disk" from the mirror's raw size fields. */
export function specLine(server: AssetRow): string {
  const parts: string[] = []
  if (server.vcpus) parts.push(`${server.vcpus} vCPU`)
  if (server.memory_megabytes) parts.push(`${formatMemory(server.memory_megabytes)} RAM`)
  if (server.disk_gigabytes) parts.push(`${server.disk_gigabytes} GB Disk`)
  return parts.join(', ')
}

/** "IN" → 🇮🇳 via regional-indicator symbols; empty for missing/invalid codes. */
export function flagEmoji(countryCode?: string | null): string {
  if (!countryCode || !/^[A-Za-z]{2}$/.test(countryCode)) return ''
  const A = 0x1f1e6
  const code = countryCode.toUpperCase()
  return String.fromCodePoint(A + code.charCodeAt(0) - 65, A + code.charCodeAt(1) - 65)
}

// Frappe Float columns default to 0, so a region with no coordinates comes back
// as 0/0 ("null island") — treat that as "not placed on the map". Such regions
// still list normally; they just don't pin.
export function hasMapCoords(region: Pick<Region, 'latitude' | 'longitude'>): boolean {
  const { latitude, longitude } = region
  if (latitude == null || longitude == null) return false
  return !(latitude === 0 && longitude === 0)
}

/** The human label for a region, falling back to its code. */
export function regionLabel(region: Pick<Region, 'region' | 'display_name'>): string {
  return region.display_name || region.region
}

/** "Falkenstein, Germany" + "Nuremberg, Germany" → "Germany"; one label keeps
 * its full name; mixed countries fall back to a neutral label. */
export function locationLabel(labels: string[]): string {
  const unique = [...new Set(labels)]
  if (unique.length === 1) return unique[0]
  const countries = [...new Set(unique.map((label) => label.split(',').pop()!.trim()))]
  return countries.length === 1 ? countries[0] : 'This area'
}

/** A server placed on the map — everything its pin and hover card show. */
export interface MapPin {
  id: string
  name: string
  lat: number
  lng: number
  provider: string | null
  visual: ServerVisual
  /** Clean "Mumbai, India" — cluster titles derive the country from it. */
  regionLabel: string
  /** Flag emoji for the hover card's region line ('' when unknown). */
  flag: string
  specs: string
  publicIpv4: string | null
  plan: string | null
  frappeVersion: string | null
  /** The raw row, for the actions menu the page wires in. */
  server: AssetRow
}

/** An empty Active region — a "+" affordance on the map. */
export interface MapSpot {
  /** The Atlas Instance region code (what new-server routes on). */
  id: string
  lat: number
  lng: number
  provider: string | null
  regionLabel: string
  flag: string
}
