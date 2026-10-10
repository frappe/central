import type { CSSProperties } from 'vue'
import type { VirtualMachineRow } from '@/composables/useServers'
import { displayStatus } from '@/lib/status'
import { formatMemory } from '@/lib/units'
import type { Region } from '@/types/Region'

// Display mapping for the servers map: one place that turns a Virtual Machine's mirror
// status into what the map shows (label, badge, dot colour, motion). Terminated
// servers never reach the map — useServerMapData filters them out.

type BadgeTheme = 'green' | 'gray' | 'amber' | 'red' | 'blue'

/** How a status moves: `progress` is work under way, `alert` needs a person. */
export type ServerMotion = 'none' | 'progress' | 'alert'

export interface ServerVisual {
	/** Stable key the status filter matches on. */
	key:
		| 'active'
		| 'settingUp'
		| 'paused'
		| 'stopped'
		| 'broken'
		| 'resizing'
		| 'terminating'
	label: string
	badgeTheme: BadgeTheme
	/** CSS variable for the status dot, and for the motion ring around a pin. */
	dot: string
	motion: ServerMotion
}

const VISUALS: Record<ServerVisual['key'], ServerVisual> = {
	active: {
		key: 'active',
		label: 'Active',
		badgeTheme: 'green',
		dot: 'var(--ink-green-6)',
		motion: 'none',
	},
	settingUp: {
		key: 'settingUp',
		label: 'Setting up',
		badgeTheme: 'amber',
		dot: 'var(--ink-amber-6)',
		motion: 'progress',
	},
	paused: {
		key: 'paused',
		label: 'Paused',
		badgeTheme: 'gray',
		dot: 'var(--ink-gray-5)',
		motion: 'none',
	},
	stopped: {
		key: 'stopped',
		label: 'Stopped',
		badgeTheme: 'gray',
		dot: 'var(--ink-gray-5)',
		motion: 'none',
	},
	broken: {
		key: 'broken',
		label: 'Broken',
		badgeTheme: 'red',
		dot: 'var(--ink-red-6)',
		motion: 'alert',
	},
	resizing: {
		key: 'resizing',
		label: 'Resizing',
		badgeTheme: 'amber',
		dot: 'var(--ink-amber-6)',
		motion: 'progress',
	},
	terminating: {
		key: 'terminating',
		label: 'Terminating',
		badgeTheme: 'red',
		dot: 'var(--ink-red-6)',
		motion: 'progress',
	},
}

// Higher wins when a cluster shows one member's motion for the whole group.
const MOTION_SEVERITY: Record<ServerMotion, number> = {
	none: 0,
	progress: 1,
	alert: 3,
}

function severityOf(visual: ServerVisual): number {
	// Destructive work outranks routine work, but not a failure.
	return MOTION_SEVERITY[visual.motion] + (visual.key === 'terminating' ? 1 : 0)
}

/** The member visual a cluster shows: the most severe motion, or null when all are idle. */
function getClusterActivity(visuals: ServerVisual[]): ServerVisual | null {
	const top = visuals.reduce<ServerVisual | null>(
		(best, visual) =>
			!best || severityOf(visual) > severityOf(best) ? visual : best,
		null,
	)
	return top && top.motion !== 'none' ? top : null
}

/** A live action's transitional label, shown from the click until the mirror confirms. */
function pendingVisual(label: string): ServerVisual {
	if (label === 'Resizing') return VISUALS.resizing
	if (label === 'Terminating') return VISUALS.terminating
	return { ...VISUALS.settingUp, label }
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

export function statusVisual(server: VirtualMachineRow): ServerVisual {
	// A live action wins, so the row never looks like nothing happened.
	if (server.pending_action) return pendingVisual(server.pending_action)
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
export function specLine(server: VirtualMachineRow): string {
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
	/** The raw server row, for the server actions menu the page wires in. */
	server?: VirtualMachineRow
	// — Site-only (undefined on server pins) —
	site?: { name: string; url: string | null; pending_action?: string | null }
}

/** A server or site decorated into one list/map shape. A site is a 1:1-backed VM,
 *  so it wears the same provider avatar and lists in the same sorted stream as a
 *  server; only its `server`/`site` payload and ⋯ actions differ. */
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
	server?: VirtualMachineRow
	site?: { name: string; url: string | null; pending_action?: string | null }
}

/** An empty Active region — a "+" affordance on the map. */
export interface MapSpot {
	/** The Region code (what new-server routes on). */
	id: string
	lat: number
	lng: number
	provider: string | null
	regionLabel: string
	flag: string
}

/** An empty region on the fleet map, with what its create card needs. */
export interface RegionSpot extends MapSpot {
	/** False while Central can't reach the region; it takes no new servers then. */
	isReachable: boolean
}

// — Map geometry, clustering and card placement. Pure; useMapViewport owns the viewport.

// The equirectangular frame the WorldDots asset was generated on.
export const MAP_WIDTH = 879
export const MAP_HEIGHT = 443
const LAT_TOP = 83
const LAT_BOTTOM = -56
// Clustering thresholds, in screen pixels.
const SERVER_CLUSTER_PX = 46
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
}
export interface ClusterNode {
	type: 'cluster'
	key: string
	x: number
	y: number
	members: PlacedPin[]
	provider: string | null
	/** The most severe member visual, so the group moves like its worst server. */
	activity: ServerVisual | null
	title: string
}
export interface PlusNode {
	type: 'plus'
	key: string
	x: number
	y: number
	targets: (RegionSpot & { wx: number; wy: number })[]
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
	spots: RegionSpot[]
	markers: MapSpot[]
	selectedId: string | null
	/** Screen pixels per map unit; cluster thresholds divide by it. */
	scale: number
}

/** Cluster pins and spots (or lay out picker markers) into positioned nodes.
 *  Thresholds are in screen pixels, so groups split as the map zooms in. */
export function computeNodes({
	pins,
	spots,
	markers,
	selectedId,
	scale: k,
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
				activity: getClusterActivity(group.members.map((m) => m.visual)),
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

const CARD_MARGIN = 12

function clamp(value: number, min: number, max: number): number {
	return Math.min(Math.max(value, min), Math.max(min, max))
}

/** Place the hover card beside its node, on the side with room, inside the map. */
export function placeHoverCard(
	node: MapNode,
	at: { x: number; y: number },
	bounds: { width: number; height: number },
): CSSProperties {
	const width = node.type === 'server' ? 320 : 288
	const nodeRadius =
		node.type === 'cluster' ? 28 : node.type === 'server' ? 24 : 18
	const gap = nodeRadius + CARD_MARGIN
	const isOnLeft = at.x + gap + width > bounds.width - CARD_MARGIN
	const left = clamp(
		isOnLeft ? at.x - gap - width : at.x + gap,
		CARD_MARGIN,
		bounds.width - width - CARD_MARGIN,
	)
	// An estimate, only to keep a tall card off the bottom edge.
	const estimatedHeight =
		node.type === 'server'
			? 220
			: node.type === 'cluster'
				? 40 + node.members.length * 48
				: 160
	const top = clamp(
		at.y - 36,
		CARD_MARGIN,
		bounds.height - estimatedHeight - CARD_MARGIN,
	)
	return {
		left: `${left}px`,
		top: `${top}px`,
		width: `${width}px`,
		transformOrigin: isOnLeft ? 'right 44px' : 'left 44px',
		'--smc-dx': isOnLeft ? '6px' : '-6px',
	} as CSSProperties
}

// A site's status mapped onto the shared server visual vocabulary, so the unified
// servers list (and its status filter) can treat a site like the VM it is.
export function siteVisual(
	status: string,
	pendingAction?: string | null,
): ServerVisual {
	if (pendingAction) return pendingVisual(pendingAction)
	// A site mirrors its machine's status, so the two share one vocabulary.
	return STATUS_VISUAL[status] ?? VISUALS.settingUp
}
