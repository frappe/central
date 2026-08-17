import type { AssetRow } from '@/composables/useServers'
import { formatMemory } from '@/lib/format'
import { displayStatus, isResizing } from '@/lib/status'
import type { Region } from '@/types/Region'

// Display mapping for the servers map: one place that turns an Asset's mirror
// status into what the map shows (label, badge, dot colour, pulse). Terminated
// assets never reach the map — useServerMapData filters them out.

type BadgeTheme = 'green' | 'gray' | 'amber' | 'red' | 'blue'

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
	active: {
		key: 'active',
		label: 'Active',
		badgeTheme: 'green',
		dot: 'var(--ink-green-6)',
		pulse: false,
	},
	settingUp: {
		key: 'settingUp',
		label: 'Setting up',
		badgeTheme: 'amber',
		dot: 'var(--ink-amber-6)',
		pulse: false,
	},
	paused: {
		key: 'paused',
		label: 'Paused',
		badgeTheme: 'gray',
		dot: 'var(--ink-gray-5)',
		pulse: false,
	},
	stopped: {
		key: 'stopped',
		label: 'Stopped',
		badgeTheme: 'gray',
		dot: 'var(--ink-gray-5)',
		pulse: false,
	},
	broken: {
		key: 'broken',
		label: 'Broken',
		badgeTheme: 'red',
		dot: 'var(--ink-red-6)',
		pulse: true,
	},
	resizing: {
		key: 'resizing',
		label: 'Resizing',
		badgeTheme: 'amber',
		dot: 'var(--ink-amber-6)',
		pulse: false,
	},
}

// Mirror status → visual. Keyed by string because Atlas can report statuses
// beyond the known set — anything unmapped reads as "Setting up" (transient).
const STATUS_VISUAL: Record<string, ServerVisual> = {
	Running: VISUALS.active,
	Pending: VISUALS.settingUp,
	Provisioning: VISUALS.settingUp,
	Deploying: VISUALS.settingUp,
	Paused: VISUALS.paused,
	Stopped: VISUALS.stopped,
	Failed: VISUALS.broken,
}

export function statusVisual(server: AssetRow): ServerVisual {
	// A live action wins: show its transitional label, pulsing to read as "working now",
	// from the click until the mirror confirms — so the row never looks like nothing happened.
	if (server.pending_action) {
		return {
			key: 'settingUp',
			label: server.pending_action,
			badgeTheme: 'amber',
			dot: 'var(--ink-amber-6)',
			pulse: true,
		}
	}
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

/** "4 vCPU, 8 GB RAM, 75 GB Disk" from the mirror's raw size fields. */
export function specLine(server: AssetRow): string {
	const parts: string[] = []
	if (server.vcpus) parts.push(`${server.vcpus} vCPU`)
	if (server.memory_megabytes)
		parts.push(`${formatMemory(server.memory_megabytes)} RAM`)
	if (server.disk_gigabytes) parts.push(`${server.disk_gigabytes} GB Disk`)
	return parts.join(', ')
}

/** "IN" → 🇮🇳 via regional-indicator symbols; empty for missing/invalid codes. */
export function flagEmoji(countryCode?: string | null): string {
	if (!countryCode || !/^[A-Za-z]{2}$/.test(countryCode)) return ''
	const A = 0x1f1e6
	const code = countryCode.toUpperCase()
	return String.fromCodePoint(
		A + code.charCodeAt(0) - 65,
		A + code.charCodeAt(1) - 65,
	)
}

// Frappe Float columns default to 0, so a region with no coordinates comes back
// as 0/0 ("null island") — treat that as "not placed on the map". Such regions
// still list normally; they just don't pin.
export function hasMapCoords(
	region: Pick<Region, 'latitude' | 'longitude'>,
): boolean {
	const { latitude, longitude } = region
	if (latitude == null || longitude == null) return false
	return !(latitude === 0 && longitude === 0)
}

/** The human label for a region, falling back to its code. */
export function regionLabel(
	region: Pick<Region, 'region' | 'display_name'>,
): string {
	return region.display_name || region.region
}

/** "Falkenstein, Germany" + "Nuremberg, Germany" → "Germany"; one label keeps
 * its full name; mixed countries fall back to a neutral label. */
export function locationLabel(labels: string[]): string {
	const unique = [...new Set(labels)]
	if (unique.length === 1) return unique[0]
	const countries = [
		...new Set(unique.map((label) => label.split(',').pop()!.trim())),
	]
	return countries.length === 1 ? countries[0] : 'This area'
}

/** A VM placed on the map — a server or a site (each a 1:1-backed VM). Everything its
 *  pin and hover card show. Server-only fields (specs/IP/plan/version/`server`) are
 *  absent on sites, which instead carry `site`; both share id/provider/visual/region. */
export interface MapPin {
	kind: 'server' | 'site'
	id: string
	name: string
	lat: number
	lng: number
	provider: string | null
	visual: ServerVisual
	/** Region code — the region a cluster's "new server" routes to. */
	cluster: string
	/** Clean "Mumbai, India" — cluster titles derive the country from it. */
	regionLabel: string
	/** Flag emoji for the hover card's region line ('' when unknown). */
	flag: string
	/** Secondary line: a server's spec line, or a site's FQDN. */
	specs: string
	// — Server-only (undefined on site pins) —
	publicIpv4?: string | null
	plan?: string | null
	frappeVersion?: string | null
	/** The raw asset row, for the server actions menu the page wires in. */
	server?: AssetRow
	// — Site-only (undefined on server pins) —
	site?: { name: string; url: string | null }
}

/** A server or site decorated into one list/map shape. A site is a 1:1-backed VM,
 *  so it wears the same provider avatar and lists in the same sorted stream as a
 *  server; only its `asset`/`site` payload and ⋯ actions differ. */
export interface ResourceRow {
	kind: 'server' | 'site'
	id: string
	name: string
	visual: ServerVisual
	specs: string
	cluster: string
	region: Region | undefined
	regionLabel: string
	flag: string
	provider: string | null
	asset?: AssetRow
	site?: { name: string; url: string | null }
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

// — Map geometry & clustering. Pure: the ServerMap component owns the stateful
//   viewport (pan/zoom/RAF); everything here is deterministic from its inputs.

// Equirectangular projection matching the WorldDots asset, generated on this exact
// frame — lat/lng from Atlas Instances line up with the dots.
export const MAP_WIDTH = 879
export const MAP_HEIGHT = 443
const LAT_TOP = 83
const LAT_BOTTOM = -56
// User zoom is gone (hover cards carry the detail); this caps how far picker
// mode may zoom while framing its marker set.
export const MAX_ZOOM = 5
// export const ZOOM_STEP = 1.7 // restored with the map's zoom controls
// Past this zoom, servers sharing a spot stop counting ("3") and fan out into
// an overlapping avatar stack — only reachable via the picker's marker fit.
export const STACK_ZOOM = 2.8

// Greedy proximity-cluster thresholds in SCREEN pixels (divided by scale k), so
// groups split apart naturally as you zoom in.
const SERVER_CLUSTER_PX = 46
const STACK_FAN_PX = 24
const SPOT_UNDER_SERVER_PX = 36
const SPOT_CLUSTER_PX = 30

export function project(point: { lat: number; lng: number }): {
	x: number
	y: number
} {
	return {
		x: ((point.lng + 180) / 360) * MAP_WIDTH,
		y: ((LAT_TOP - point.lat) / (LAT_TOP - LAT_BOTTOM)) * MAP_HEIGHT,
	}
}

export type PlacedPin = MapPin & { wx: number; wy: number }
export type PlacedSpot = MapSpot & { wx: number; wy: number }

export interface ServerNode {
	type: 'server'
	key: string
	x: number
	y: number
	pin: PlacedPin
	stacked?: boolean
	stackZ?: number
}
export interface ClusterNode {
	type: 'cluster'
	key: string
	x: number
	y: number
	members: PlacedPin[]
	provider: string | null
	broken: boolean
	title: string
}
export interface PlusNode {
	type: 'plus'
	key: string
	x: number
	y: number
	targets: PlacedSpot[]
	title: string
}
export interface MarkerNode {
	type: 'marker'
	key: string
	x: number
	y: number
	marker: PlacedSpot
	selected: boolean
}
export type MapNode = ServerNode | ClusterNode | PlusNode | MarkerNode

interface Group<T> {
	x: number
	y: number
	members: T[]
}

function worldOf<T extends { lat: number; lng: number }>(
	point: T,
): T & { wx: number; wy: number } {
	const { x, y } = project(point)
	return { ...point, wx: x, wy: y }
}

function groupBy<T extends { wx: number; wy: number }>(
	items: T[],
	threshold: number,
): Group<T>[] {
	const groups: Group<T>[] = []
	for (const item of items) {
		let best: Group<T> | null = null
		let bestD = Infinity
		for (const group of groups) {
			const d = Math.hypot(group.x - item.wx, group.y - item.wy)
			if (d < threshold && d < bestD) {
				best = group
				bestD = d
			}
		}
		if (best) {
			best.members.push(item)
			best.x =
				best.members.reduce((sum, m) => sum + m.wx, 0) / best.members.length
			best.y =
				best.members.reduce((sum, m) => sum + m.wy, 0) / best.members.length
		} else {
			groups.push({ x: item.wx, y: item.wy, members: [item] })
		}
	}
	return groups
}

function dominantProvider(members: PlacedPin[]): string | null {
	const counts: Record<string, number> = {}
	for (const m of members) {
		const key = m.provider ?? ''
		counts[key] = (counts[key] || 0) + 1
	}
	return members.reduce((a, b) =>
		counts[b.provider ?? ''] > counts[a.provider ?? ''] ? b : a,
	).provider
}

export interface ComputeNodesInput {
	pins: MapPin[]
	spots: MapSpot[]
	markers: MapSpot[]
	selectedId: string | null
	/** Current screen scale (base × zoom); cluster thresholds divide by it. */
	k: number
	zoom: number
}

/** Cluster the map's pins/spots (or lay out picker markers) into positioned
 *  nodes. Greedy proximity clustering in world units, thresholds fixed in screen
 *  pixels so groups split as you zoom in. */
export function computeNodes({
	pins,
	spots,
	markers,
	selectedId,
	k,
	zoom,
}: ComputeNodesInput): MapNode[] {
	if (!k) return []
	// Picker mode: every marker is its own node (a handful of regions — no
	// clustering), keyed on selection so the dot↔pin swap animates.
	if (markers.length) {
		return markers.map((marker) => {
			const placed = worldOf(marker)
			return {
				type: 'marker' as const,
				key: `m-${marker.id}-${marker.id === selectedId}`,
				x: placed.wx,
				y: placed.wy,
				marker: placed,
				selected: marker.id === selectedId,
			}
		})
	}
	const placedPins = pins.map(worldOf)
	const serverGroups = groupBy(placedPins, SERVER_CLUSTER_PX / k)
	const out: MapNode[] = []
	for (const group of serverGroups) {
		if (group.members.length === 1) {
			out.push({
				type: 'server',
				key: `s-${group.members[0].id}`,
				x: group.x,
				y: group.y,
				pin: group.members[0],
			})
		} else if (zoom >= STACK_ZOOM) {
			const gap = STACK_FAN_PX / k
			group.members.forEach((m, i) => {
				out.push({
					type: 'server',
					key: `s-${m.id}`,
					x: group.x + (i - (group.members.length - 1) / 2) * gap,
					y: group.y,
					pin: m,
					stacked: true,
					stackZ: group.members.length - i,
				})
			})
		} else {
			out.push({
				type: 'cluster',
				key: `c-${group.members
					.map((m) => m.id)
					.sort()
					.join('.')}`,
				x: group.x,
				y: group.y,
				members: group.members,
				provider: dominantProvider(group.members),
				broken: group.members.some((m) => m.visual.pulse),
				title: locationLabel(group.members.map((m) => m.regionLabel)),
			})
		}
	}
	// Empty regions collapse into one + per spot. A region under a server node is
	// dropped individually, so its neighbours still show.
	const placedSpots = spots
		.map(worldOf)
		.filter(
			(s) =>
				!serverGroups.some(
					(g) => Math.hypot(g.x - s.wx, g.y - s.wy) < SPOT_UNDER_SERVER_PX / k,
				),
		)
	for (const group of groupBy(placedSpots, SPOT_CLUSTER_PX / k)) {
		out.push({
			type: 'plus',
			key: `p-${group.members
				.map((s) => s.id)
				.sort()
				.join('.')}`,
			x: group.x,
			y: group.y,
			targets: group.members,
			title: locationLabel(group.members.map((s) => s.regionLabel)),
		})
	}
	return out
}

// A site's status mapped onto the shared server visual vocabulary, so the unified
// assets list (and its status filter) can treat a site like the VM it is.
export function siteVisual(
	status: string,
	pendingAction?: string | null,
): ServerVisual {
	// A live site action wins, same as servers — show its label, pulsing, until the mirror confirms.
	if (pendingAction)
		return {
			key: 'settingUp',
			label: pendingAction,
			badgeTheme: 'amber',
			dot: 'var(--ink-amber-6)',
			pulse: true,
		}
	if (status === 'Running')
		return {
			key: 'active',
			label: 'Running',
			badgeTheme: 'green',
			dot: 'var(--ink-green-6)',
			pulse: false,
		}
	if (status === 'Failed')
		return {
			key: 'broken',
			label: 'Failed',
			badgeTheme: 'red',
			dot: 'var(--ink-red-6)',
			pulse: true,
		}
	return {
		key: 'settingUp',
		label: status,
		badgeTheme: 'amber',
		dot: 'var(--ink-amber-6)',
		pulse: false,
	}
}
