<script setup lang="ts">
import {
	type CSSProperties,
	computed,
	onBeforeUnmount,
	onMounted,
	ref,
	watch,
} from 'vue'
import MapHoverCard from '@/components/servers/MapHoverCard.vue'
import ProviderAvatar from '@/components/servers/ProviderAvatar.vue'
import WorldDots from '@/components/servers/WorldDots.vue'
import {
	computeNodes,
	MAP_HEIGHT,
	MAP_WIDTH,
	MAX_ZOOM,
	type MapNode,
	type MapPin,
	type MapSpot,
	project,
} from '@/lib/serverMap'

// The interactive servers map, ported from the FC V2 prototype. Purely
// presentational: pins/spots arrive display-ready from the page, actions leave
// as emits (plus the card-actions slot for the server card's ⋯ menu).

const props = withDefaults(
	defineProps<{
		pins?: MapPin[]
		spots?: MapSpot[]
		/** Region-picker mode: render these as selectable dots instead of pins/spots. */
		markers?: MapSpot[]
		/** The picked marker — drawn as the provider-logo pin. */
		selectedId?: string | null
		/** Server id hovered elsewhere (the side panel) — bumps its node. */
		highlightId?: string | null
		/** Width a panel overlays on the right edge (px) — cards clamp to the rest. */
		panelOffset?: number
		/** False = picker mode; the map frames its markers itself. */
		interactive?: boolean
		/** Show create affordances inside cards (page gates on server:create). */
		allowCreate?: boolean
		/** Show direct bench-open affordances inside cluster cards. */
		allowOpen?: boolean
		/** Site name currently being opened — spins its cluster-card open button. */
		openingSite?: string | null
	}>(),
	{
		pins: () => [],
		spots: () => [],
		markers: () => [],
		selectedId: null,
		highlightId: null,
		panelOffset: 0,
		interactive: true,
		allowCreate: false,
		allowOpen: false,
		openingSite: null,
	},
)

const emit = defineEmits<{
	/** A pin (or a cluster-card row) was chosen — page opens the site/server. */
	open: [id: string]
	/** A server cluster-card row's open-bench action was chosen. */
	'open-server': [server: NonNullable<MapPin['server']>]
	/** A site pin/cluster-card row's open-live-site action was chosen. */
	'open-site': [name: string]
	/** A + spot was chosen — the Atlas Instance region to create in. */
	'new-server': [region: string]
	/** A cluster was clicked; the page may narrow its list to these servers. */
	'cluster-open': [payload: { ids: string[]; label: string }]
	/** A picker marker was chosen. */
	select: [region: string]
}>()

// Aliases for the projection frame the lib owns, so the framing math below reads
// unchanged. project() and computeNodes() (clustering) live in lib/serverMap.
const W = MAP_WIDTH
const H = MAP_HEIGHT
const MAX_Z = MAX_ZOOM
// User zoom and pan are retired: the map contain-fits the world and hover
// cards carry the detail. The implementation stays commented in place rather
// than deleted, so bringing it back is uncommenting these blocks, the handlers
// on the root element, and the controls at the end of the template — plus
// re-exporting ZOOM_STEP from lib/serverMap.
// const STEP = ZOOM_STEP

// Contain-fit the world. There is no user zoom/pan; the zoom/translate state
// below exists only so picker mode can frame its marker set.
const el = ref<HTMLDivElement | null>(null)
const cw = ref(0)
const ch = ref(0)
const zoom = ref(1)
const tx = ref(0)
const ty = ref(0)
// const dragging = ref(false)
// const wheeling = ref(false)
const focusing = ref(false)

const base = computed(() =>
	cw.value && ch.value ? Math.min(cw.value / W, ch.value / H) : 0,
)
const k = computed(() => base.value * zoom.value)

// Transitions stay off until the first layout lands — the map must appear in
// place instantly, not zoom in from nothing.
const ready = ref(false)
watch(base, (v) => {
	if (v && !ready.value)
		requestAnimationFrame(() =>
			requestAnimationFrame(() => (ready.value = true)),
		)
})

// A container resize is not a reframe: the map must track its box exactly, not
// glide 450ms behind it. Every size change disarms the transitions for the
// frames it takes to land, then re-arms them for flyTo and reclustering. Without
// this, a container that settles in two steps (which is what entering the page
// does) plays the second step as a zoom-in from the first.
const sizing = ref(false)
let sizeRaf = 0
function measure(w: number, h: number): void {
	if (w === cw.value && h === ch.value) return
	sizing.value = true
	cw.value = w
	ch.value = h
	cancelAnimationFrame(sizeRaf)
	// Two frames, in this order: commit the crisp raster while the transitions
	// are still disarmed, then re-arm them. Committing it in the same patch that
	// re-arms them would play the width/height correction as a 450ms animation.
	sizeRaf = requestAnimationFrame(() => {
		rasterK.value = k.value
		sizeRaf = requestAnimationFrame(() => (sizing.value = false))
	})
}

// The dotted world is one path of ~2000 subpaths. Sizing the SVG in pixels means
// the browser re-rasterizes all of it, and a sidebar collapse hands us a new
// size on every frame for 300ms — 20 rasters for one gesture. So a resize holds
// the last raster and takes the difference as a scale instead: same geometry to
// the pixel, but the compositor carries the frames. The crisp raster lands once
// the size settles. Everything else that moves k (picker-mode flyTo) keeps
// re-rasterizing per frame, which is what keeps the dots sharp while it glides.
const rasterK = ref(0)
watch([k, sizing], ([, isSizing]) => {
	if (!isSizing) rasterK.value = k.value
})

let ro: ResizeObserver | undefined
onMounted(() => {
	// Measure before the first paint. The ResizeObserver's own first callback
	// arrives a frame late, which would render one frame of a zero-sized map.
	if (el.value) {
		const r = el.value.getBoundingClientRect()
		measure(r.width, r.height)
	}
	ro = new ResizeObserver(([entry]) => {
		measure(entry.contentRect.width, entry.contentRect.height)
	})
	if (el.value) ro.observe(el.value)
})
onBeforeUnmount(() => {
	ro?.disconnect()
	// Tear down every timer/RAF this component owns — the flyTo RAF loop
	// (focusRaf) keeps writing zoom/tx/ty after unmount otherwise, and the
	// hover debounces fire into a dead component.
	cancelAnimationFrame(focusRaf)
	cancelAnimationFrame(sizeRaf)
	// window.clearTimeout(wheelT)
	window.clearTimeout(showT)
	window.clearTimeout(hideT)
})

function clampPan(): void {
	const w = W * k.value
	const h = H * k.value
	tx.value =
		w <= cw.value
			? (cw.value - w) / 2
			: Math.min(0, Math.max(cw.value - w, tx.value))
	ty.value =
		h <= ch.value
			? (ch.value - h) / 2
			: Math.min(0, Math.max(ch.value - h, ty.value))
}
watch([base, cw, ch], clampPan)

const mapStyle = computed(() => {
	// Falls back to k until the first raster is committed, so the map is never
	// sized from a zero.
	const rk = rasterK.value || k.value
	const scale = rk ? k.value / rk : 1
	return {
		transform:
			scale === 1
				? `translate3d(${tx.value}px, ${ty.value}px, 0)`
				: `translate3d(${tx.value}px, ${ty.value}px, 0) scale(${scale})`,
		// The scale rides on top of the translate, so it has to grow from the
		// corner the translate placed — not from the middle of the map.
		transformOrigin: '0 0',
		width: `${W * rk}px`,
		height: `${H * rk}px`,
	}
})

// function zoomAt(ax: number, ay: number, factor: number): void {
// 	cancelFocus()
// 	const zNew = Math.min(MAX_Z, Math.max(1, zoom.value * factor))
// 	if (zNew === zoom.value) return
// 	const kOld = k.value
// 	const kNew = base.value * zNew
// 	tx.value = ax - ((ax - tx.value) / kOld) * kNew
// 	ty.value = ay - ((ay - ty.value) / kOld) * kNew
// 	zoom.value = zNew
// 	hideCard()
// 	clampPan()
// }
// function zoomStep(dir: number): void {
// 	zoomAt(cw.value / 2, ch.value / 2, dir > 0 ? STEP : 1 / STEP)
// }

// Reframe in one continuous move. Driven frame-by-frame rather than by CSS:
// zoom interpolates in log space so the combined motion never swings.
let focusRaf = 0
function cancelFocus(): void {
	cancelAnimationFrame(focusRaf)
	focusing.value = false
}
function flyTo(wx: number, wy: number, z1: number): void {
	cancelFocus()
	hideCard()
	const z0 = zoom.value
	const from = { sx: wx * k.value + tx.value, sy: wy * k.value + ty.value }
	const to = { sx: cw.value / 2, sy: ch.value / 2 }
	const D = 600
	const start = performance.now()
	const ease = (t: number) =>
		t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
	focusing.value = true
	const frame = (now: number) => {
		const e = ease(Math.min(1, (now - start) / D))
		zoom.value = z0 * Math.pow(z1 / z0, e)
		tx.value = from.sx + (to.sx - from.sx) * e - wx * k.value
		ty.value = from.sy + (to.sy - from.sy) * e - wy * k.value
		clampPan()
		if (now - start < D) focusRaf = requestAnimationFrame(frame)
		else focusing.value = false
	}
	focusRaf = requestAnimationFrame(frame)
}

// Focus a node in one continuous move: zoom to (at least) the stack level while
// the node glides to the viewport centre.
// function focusOn(n: MapNode): void {
// 	flyTo(n.x, n.y, Math.min(MAX_Z, Math.max(zoom.value, STEP * STEP)))
// }

// Picker mode frames itself: fit the marker set (new provider = new frame).
// First layout lands in place; later changes glide.
function fitMarkers(): void {
	if (!base.value) return
	const pts = props.markers.map(project)
	if (!pts.length) {
		// A provider with no placed regions frames the whole world instead of
		// staying wherever the last fit left the map.
		if (!props.interactive && ready.value && zoom.value > 1)
			flyTo(W / 2, H / 2, 1)
		return
	}
	const pad = 48
	const xs = pts.map((p) => p.x)
	const ys = pts.map((p) => p.y)
	const bw = Math.max(...xs) - Math.min(...xs) + pad * 2
	const bh = Math.max(...ys) - Math.min(...ys) + pad * 2
	const z1 = Math.min(
		MAX_Z,
		Math.max(1, Math.min(cw.value / bw, ch.value / bh) / base.value),
	)
	const wx = (Math.min(...xs) + Math.max(...xs)) / 2
	const wy = (Math.min(...ys) + Math.max(...ys)) / 2
	if (!ready.value) {
		zoom.value = z1
		tx.value = cw.value / 2 - wx * k.value
		ty.value = ch.value / 2 - wy * k.value
		clampPan()
		return
	}
	flyTo(wx, wy, z1)
}
watch([() => props.markers, base], fitMarkers)

// — Drag to pan (only when zoomed in). A real click is distinguished from a
//   drag by a 4px slop; after a drag the trailing click is swallowed.
// interface DragState {
// 	x: number
// 	y: number
// 	tx: number
// 	ty: number
// 	id: number
// 	moved: boolean
// }
// let drag: DragState | null = null
// let suppressClick = false
function closestOf(e: Event, selector: string): Element | null {
	return (e.target as Element | null)?.closest(selector) ?? null
}
function onDown(e: PointerEvent): void {
	if (e.button !== 0 || !props.interactive) return
	// A locked card (its ⋯ menu was opened) closes on any press outside it.
	if (cardLocked.value && !closestOf(e, '[data-map-card]')) hideCard()
	// if (zoom.value <= 1) return
	// if (closestOf(e, '[data-map-card],[data-map-controls]')) return
	// drag = {
	// 	x: e.clientX,
	// 	y: e.clientY,
	// 	tx: tx.value,
	// 	ty: ty.value,
	// 	id: e.pointerId,
	// 	moved: false,
	// }
}
// function onMove(e: PointerEvent): void {
// 	if (!drag) return
// 	const dx = e.clientX - drag.x
// 	const dy = e.clientY - drag.y
// 	if (!drag.moved && Math.hypot(dx, dy) < 4) return
// 	if (!drag.moved) {
// 		drag.moved = true
// 		dragging.value = true
// 		cancelFocus() // don't fight the user for the viewport
// 		hideCard()
// 		el.value?.setPointerCapture?.(drag.id)
// 	}
// 	tx.value = drag.tx + dx
// 	ty.value = drag.ty + dy
// 	clampPan()
// }
// function onUp(): void {
// 	if (drag?.moved) {
// 		suppressClick = true
// 		setTimeout(() => (suppressClick = false), 0)
// 	}
// 	drag = null
// 	dragging.value = false
// }
// function onDblClick(e: MouseEvent): void {
// 	if (!props.interactive) return
// 	if (closestOf(e, '[data-map-card],[data-map-controls]')) return
// 	if (!el.value) return
// 	const r = el.value.getBoundingClientRect()
// 	zoomAt(e.clientX - r.left, e.clientY - r.top, STEP)
// }

// Trackpad: pinch (ctrl+wheel) zooms at the cursor; two-finger scroll pans when
// zoomed in. Both move without the zoom transition.
// let wheelT: number | undefined
// function onWheel(e: WheelEvent): void {
// 	if (!props.interactive) return
// 	const pinch = e.ctrlKey || e.metaKey
// 	if (!pinch && zoom.value <= 1) return
// 	e.preventDefault()
// 	wheeling.value = true
// 	cancelFocus()
// 	window.clearTimeout(wheelT)
// 	wheelT = window.setTimeout(() => (wheeling.value = false), 140)
// 	hideCard()
// 	if (pinch) {
// 		if (!el.value) return
// 		const r = el.value.getBoundingClientRect()
// 		zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.01))
// 	} else {
// 		tx.value -= e.deltaX
// 		ty.value -= e.deltaY
// 		clampPan()
// 	}
// }

// Cluster the fleet into positioned nodes — pure, in lib/serverMap. Reclusters as
// k/zoom change so groups split apart on zoom-in.
const nodes = computed<MapNode[]>(() =>
	computeNodes({
		pins: props.pins,
		spots: props.spots,
		markers: props.markers,
		selectedId: props.selectedId ?? null,
		k: k.value,
		zoom: zoom.value,
	}),
)

function screenOf(n: { x: number; y: number }): { sx: number; sy: number } {
	return { sx: tx.value + n.x * k.value, sy: ty.value + n.y * k.value }
}

// The node that holds a given server id — its own pin, the cluster it grouped
// into, or its picker marker.
function nodeForServer(id: string): MapNode | undefined {
	return nodes.value.find(
		(node) =>
			(node.type === 'server' && node.pin.id === id) ||
			(node.type === 'cluster' && node.members.some((m) => m.id === id)) ||
			(node.type === 'marker' && node.marker.id === id),
	)
}

const highlightKey = computed(() =>
	props.highlightId ? nodeForServer(props.highlightId)?.key || null : null,
)

function isHot(n: MapNode): boolean {
	return n.key === hoverKey.value || n.key === highlightKey.value
}

// Stacking order rides the outer wrapper; the position transform rides an inner
// one. They must stay split: TransitionGroup's FLIP pass measures its own
// children and, for any it thinks moved, clears their inline transform outright
// (runtime-dom sets `style.transform = ''`). Vue never rewrites the value
// afterwards — its style patch compares against the vnode, which still holds the
// transform it wrote — so the node is stranded at the map's top-left corner
// until some later patch changes the string. With the transform on an inner
// element the wrapper's own rect never moves, so the FLIP pass finds nothing to
// translate. (Safari lost this race on client-side navigation into the page:
// its ResizeObserver lands a second, corrected size after the nodes have already
// been placed, so that final reposition went through FLIP and stuck.)
function zStyle(n: MapNode): CSSProperties {
	const zBase =
		n.type === 'marker'
			? n.selected
				? 21
				: 12
			: n.type === 'plus'
				? 10
				: n.type === 'cluster'
					? 21
					: 20
	return {
		zIndex: isHot(n) ? 30 : zBase + (n.type === 'server' ? n.stackZ || 0 : 0),
	}
}
function posStyle(n: MapNode): CSSProperties {
	const { sx, sy } = screenOf(n)
	return { transform: `translate3d(${sx}px, ${sy}px, 0)` }
}

// — Hover intent: a short delay in, a grace period out so the pointer can
//   travel from node to card without the card blinking away.
const hoverKey = ref<string | null>(null)
// Opening a menu inside the card portals its items to <body>, which fires a
// mouseleave on the card. Any click inside the card locks it open; a press
// anywhere outside closes it (see onDown).
const cardLocked = ref(false)
let showT: number | undefined
let hideT: number | undefined
function enterNode(n: MapNode): void {
	if (cardLocked.value) return
	window.clearTimeout(hideT)
	window.clearTimeout(showT)
	showT = window.setTimeout(() => (hoverKey.value = n.key), 40)
}
function leaveNode(): void {
	if (cardLocked.value) return
	window.clearTimeout(showT)
	window.clearTimeout(hideT)
	hideT = window.setTimeout(() => (hoverKey.value = null), 140)
}
function cancelHide(): void {
	window.clearTimeout(hideT)
}

function hideCard(): void {
	window.clearTimeout(showT)
	window.clearTimeout(hideT)
	cardLocked.value = false
	hoverKey.value = null
}

interface CardPlacement {
	node: MapNode
	style: CSSProperties
}

const card = computed<CardPlacement | null>(() => {
	const node = hoverKey.value
		? nodes.value.find((n) => n.key === hoverKey.value)
		: undefined
	if (!node) return null
	const { sx, sy } = screenOf(node)
	const width = node.type === 'server' ? 320 : 288
	// The side panel overlays the map's right edge, so the card clamps to the
	// uncovered width.
	const visibleW = cw.value - props.panelOffset
	// Stacked avatars overlap sideways, so their card drops below instead of
	// covering the neighbours to the right.
	if (node.type === 'server' && node.stacked) {
		const left = Math.min(
			Math.max(sx - width / 2, 12),
			Math.max(12, visibleW - width - 12),
		)
		return {
			node,
			style: {
				left: `${left}px`,
				top: `${sy + 28}px`,
				width: `${width}px`,
				transformOrigin: `${sx - left}px top`,
				'--smc-dy': '-6px',
			} as CSSProperties,
		}
	}
	const r = node.type === 'cluster' ? 28 : node.type === 'server' ? 24 : 18
	let side: 'left' | 'right' = 'right'
	let left = sx + r + 12
	if (left + width > visibleW - 12) {
		side = 'left'
		left = sx - r - 12 - width
	}
	left = Math.max(12, Math.min(left, visibleW - width - 12))
	const estH =
		node.type === 'server'
			? 220
			: node.type === 'cluster'
				? 40 + node.members.length * 48
				: 160
	const top = Math.min(
		Math.max(sy - 36, 12),
		Math.max(12, ch.value - estH - 12),
	)
	return {
		node,
		style: {
			left: `${left}px`,
			top: `${top}px`,
			width: `${width}px`,
			transformOrigin: side === 'right' ? 'left 44px' : 'right 44px',
			'--smc-dx': side === 'right' ? '-6px' : '6px',
		} as CSSProperties,
	}
})

// Let the page focus the map from the side panel: glide to the node that holds
// this server (its own pin, or the cluster it's grouped into).
// function focusPin(id: string): void {
// 	const n = nodeForServer(id)
// 	if (n) focusOn(n)
// }
// defineExpose({ focusPin })

function clickNode(n: MapNode): void {
	// if (suppressClick) return
	if (n.type === 'marker') {
		emit('select', n.marker.id)
	} else if (n.type === 'server') {
		// A pin click opens the resource. A site that can't be opened yet has no
		// overview to fall back on, so keep its card open instead of a dead click.
		if (n.pin.kind === 'site' && (!props.allowOpen || !n.pin.site?.url)) {
			window.clearTimeout(showT)
			hoverKey.value = n.key
			cardLocked.value = true
			return
		}
		hideCard()
		emit('open', n.pin.id)
	} else if (n.type === 'plus') {
		emit('new-server', n.targets[0].id)
	} else {
		// A cluster's members are browsed in its hover card; clicking locks the
		// card open, and the page narrows its list if the panel is open. With
		// zoom restored this focused the map on the stack instead: focusOn(n).
		window.clearTimeout(showT)
		hoverKey.value = n.key
		cardLocked.value = true
		emit('cluster-open', { ids: n.members.map((m) => m.id), label: n.title })
	}
}
</script>

<template>
	<!-- With zoom and pan restored, this element also takes:
	     :class="[ready && !sizing && 'sm-anim', (dragging || wheeling || focusing) && 'sm-drag', dragging ? 'cursor-grabbing' : interactive && zoom > 1 ? 'cursor-grab' : '']"
	     :style="interactive && zoom > 1 ? { touchAction: 'none' } : undefined"
	     @pointermove="onMove" @pointerup="onUp" @pointercancel="onUp"
	     @dblclick="onDblClick" @wheel="onWheel" -->
	<div
		ref="el"
		class="relative isolate h-full w-full select-none overflow-hidden bg-surface-base"
		:class="[ready && !sizing && 'sm-anim', focusing && 'sm-drag']"
		@pointerdown="onDown"
	>
		<!-- Dotted world. Sized in pixels so it re-rasterizes at each zoom, except
		     across a container resize, which scales the last raster instead (see
		     rasterK); nodes ride the same curve below so they track the dots. -->
		<WorldDots
			class="sm-map sm-pos absolute left-0 top-0 block text-ink-gray-2"
			:style="mapStyle"
		/>

		<!-- Nodes: servers, clusters (2+ at one spot), and + spots for empty
         regions. Positioned in screen space; recluster as the zoom changes. -->
		<TransitionGroup name="smn">
			<div
				v-for="n in nodes"
				:key="n.key"
				class="pointer-events-none absolute left-0 top-0"
				:style="zStyle(n)"
			>
				<div class="sm-pos pointer-events-auto" :style="posStyle(n)">
					<div class="sm-center">
						<!-- Single server: provider logo + status dot -->
						<button
							v-if="n.type === 'server'"
							class="group relative block rounded-full outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
							:aria-label="`${n.pin.name} — ${n.pin.visual.label}`"
							@click="clickNode(n)"
							@mouseenter="enterNode(n)"
							@mouseleave="leaveNode"
						>
							<span
								v-if="n.pin.visual.pulse"
								class="sm-pulse absolute -inset-1.5 rounded-full"
								style="background: var(--ink-red-6)"
							/>
							<span
								class="relative block rounded-full transition-transform duration-150 ease-out group-active:scale-95"
								:class="isHot(n) && 'scale-110'"
							>
								<ProviderAvatar :provider="n.pin.provider" :size="36" />
								<!-- The badge art is inset ~2px inside its box, so the stack
	                   separator ring hugs the visible disc, not the box edge. -->
								<span
									v-if="n.stacked"
									class="pointer-events-none absolute inset-[2px] rounded-full ring-2 ring-[var(--surface-base)]"
								/>
							</span>
							<span
								class="absolute bottom-0 right-0 size-3 rounded-full border-2 border-[var(--surface-base)]"
								:style="{ background: n.pin.visual.dot }"
							/>
						</button>

						<!-- Cluster: count in a dark disc, dominant provider as a badge -->
						<button
							v-else-if="n.type === 'cluster'"
							class="group relative block rounded-full outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
							:aria-label="`${n.members.length} servers in ${n.title}`"
							@click="clickNode(n)"
							@mouseenter="enterNode(n)"
							@mouseleave="leaveNode"
						>
							<span
								class="absolute -inset-2 rounded-full transition-colors"
								:class="n.broken ? 'sm-pulse bg-surface-red-4' : 'bg-surface-gray-3 opacity-60'"
							/>
							<span
								class="relative grid size-11 place-items-center rounded-full bg-surface-gray-1 text-base font-semibold text-ink-gray-9 shadow-md transition-transform duration-150 ease-out group-active:scale-95"
								:class="isHot(n) && 'scale-105'"
							>
								{{ n.members.length }}
							</span>
							<span class="absolute -bottom-1 -right-1 block rounded-full">
								<ProviderAvatar :provider="n.provider" :size="20" />
							</span>
						</button>

						<!-- Picker marker: a quiet dot; the picked region is the provider pin -->
						<button
							v-else-if="n.type === 'marker'"
							class="group relative block rounded-full outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
							:aria-label="`Region ${n.marker.regionLabel}`"
							:title="`${n.marker.flag} ${n.marker.regionLabel}`"
							@click="clickNode(n)"
						>
							<span v-if="n.selected" class="relative block rounded-full">
								<ProviderAvatar :provider="n.marker.provider" :size="36" />
							</span>
							<span
								v-else
								class="block size-3 rounded-full transition-transform duration-150 ease-out group-hover:scale-125"
								:class="isHot(n) && 'scale-125'"
								style="background: var(--ink-gray-9)"
							/>
						</button>

						<!-- Empty region: quiet + affordance -->
						<button
							v-else
							class="grid size-7 place-items-center rounded-full border border-outline-gray-2 bg-surface-elevation-1 text-ink-gray-6 shadow-sm transition-[transform,box-shadow] duration-150 ease-out hover:shadow-md active:scale-95"
							:class="isHot(n) ? 'scale-110 shadow-md' : ''"
							:aria-label="`New server in ${n.title}`"
							@click="clickNode(n)"
							@mouseenter="enterNode(n)"
							@mouseleave="leaveNode"
						>
							<span class="lucide-plus size-3.5" />
						</button>
					</div>
				</div>
			</div>
		</TransitionGroup>

		<!-- Hover card -->
		<Transition name="smc">
			<div
				v-if="card"
				:key="card.node.key"
				data-map-card
				class="absolute z-40 rounded-7 border border-outline-gray-1 bg-surface-elevation-1 shadow-xl"
				:class="card.node.type === 'cluster' ? 'p-2' : 'p-4'"
				:style="card.style"
				@mouseenter="cancelHide"
				@mouseleave="leaveNode"
				@click.capture="cardLocked = true"
			>
				<MapHoverCard
					:node="card.node"
					:allow-create="allowCreate"
					:allow-open="allowOpen"
					:opening-site="openingSite"
					@open="emit('open', $event)"
					@open-server="emit('open-server', $event)"
					@open-site="emit('open-site', $event)"
					@new-server="emit('new-server', $event)"
				>
					<template #card-actions="{ pin }">
						<slot name="card-actions" :pin="pin" />
					</template>
				</MapHoverCard>
			</div>
		</Transition>

		<!-- Zoom controls, retired with user zoom/pan. They slid left when the
		     server panel overlaid the right edge.
		<div
			v-if="interactive"
			data-map-controls
			class="sm-controls absolute bottom-14 right-4 z-30 flex flex-col overflow-hidden rounded-6 border border-outline-gray-2 bg-surface-elevation-1 shadow-sm"
			:style="{ transform: `translateX(${-panelOffset}px)` }"
		>
			<button
				class="grid size-9 place-items-center text-ink-gray-6 transition-colors hover:bg-surface-gray-2 active:bg-surface-gray-3 disabled:pointer-events-none disabled:opacity-40"
				aria-label="Zoom in"
				:disabled="zoom >= MAX_Z"
				@click="zoomStep(1)"
			>
				<span class="lucide-zoom-in size-4" />
			</button>
			<button
				class="grid size-9 place-items-center border-t border-outline-alpha-gray-1 text-ink-gray-6 transition-colors hover:bg-surface-gray-2 active:bg-surface-gray-3 disabled:pointer-events-none disabled:opacity-40"
				aria-label="Zoom out"
				:disabled="zoom <= 1"
				@click="zoomStep(-1)"
			>
				<span class="lucide-zoom-out size-4" />
			</button>
		</div>
		-->
	</div>
</template>

<style scoped>
/* The map layer and every node share one curve, so pins track the dots
   through a reframe. Transitions only arm after the first layout (the map
   must appear in place, not animate in); the frame-driven marker fit switches
   back to direct updates. */
.sm-pos {
	will-change: transform;
}
.sm-anim .sm-pos {
	transition: transform 450ms cubic-bezier(0.77, 0, 0.175, 1);
}
.sm-anim .sm-map {
	transition:
		transform 450ms cubic-bezier(0.77, 0, 0.175, 1),
		width 450ms cubic-bezier(0.77, 0, 0.175, 1),
		height 450ms cubic-bezier(0.77, 0, 0.175, 1);
}
.sm-drag .sm-pos {
	transition: none;
}
.sm-center {
	transform: translate(-50%, -50%);
	transition:
		transform 250ms cubic-bezier(0.23, 1, 0.32, 1),
		opacity 200ms ease-out;
}

/* Recluster: merged/split nodes scale in from something, never from nothing. */
.smn-enter-from .sm-center {
	transform: translate(-50%, -50%) scale(0.6);
	opacity: 0;
}
.smn-leave-active {
	transition: opacity 140ms ease-in;
}
.smn-leave-to {
	opacity: 0;
}

/* Hover card: origin-aware scale from the node's side; exit is faster. */
.smc-enter-active {
	transition:
		opacity 150ms cubic-bezier(0.23, 1, 0.32, 1),
		transform 150ms cubic-bezier(0.23, 1, 0.32, 1);
}
.smc-enter-from {
	opacity: 0;
	transform: translate(var(--smc-dx, 0px), var(--smc-dy, 0px)) scale(0.97);
}
.smc-leave-active {
	transition: opacity 100ms ease-in;
}
.smc-leave-to {
	opacity: 0;
}

/* .sm-controls {
	transition: transform 300ms cubic-bezier(0.32, 0.72, 0, 1);
} */

.sm-pulse {
	animation: sm-pulse 1.8s ease-in-out infinite;
}
@keyframes sm-pulse {
	0%,
	100% {
		opacity: 0.28;
	}
	50% {
		opacity: 0.08;
	}
}

@media (prefers-reduced-motion: reduce) {
	.sm-pos,
	.sm-center {
		transition: none;
	}
	.sm-pulse {
		animation: none;
		opacity: 0.2;
	}
}
</style>
