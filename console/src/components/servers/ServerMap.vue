<template>
  <div
    ref="el"
    class="relative isolate h-full w-full select-none overflow-hidden bg-surface-base"
    :class="[ready && 'sm-anim', (dragging || wheeling || focusing) && 'sm-drag', dragging ? 'cursor-grabbing' : interactive && zoom > 1 ? 'cursor-grab' : '']"
    :style="interactive && zoom > 1 ? { touchAction: 'none' } : undefined"
    @pointerdown="onDown"
    @pointermove="onMove"
    @pointerup="onUp"
    @pointercancel="onUp"
    @dblclick="onDblClick"
    @wheel="onWheel"
  >
    <!-- Dotted world. One transformed layer; nodes ride the same transition
         curve below so they track the dots through zooms. -->
    <div class="sm-pos absolute left-0 top-0 origin-top-left" :style="mapStyle">
      <WorldDots class="block text-ink-gray-2" :style="{ width: `${W}px`, height: `${H}px` }" />
    </div>

    <!-- Nodes: servers, clusters (2+ at one spot), and + spots for empty
         regions. Positioned in screen space; recluster as the zoom changes. -->
    <TransitionGroup name="smn">
      <div
        v-for="n in nodes"
        :key="n.key"
        class="sm-pos absolute left-0 top-0"
        :style="posStyle(n)"
      >
        <div class="sm-center">
          <!-- Single server: provider logo + status dot -->
          <button
            v-if="n.type === 'server'"
            class="group relative block rounded-full outline-none"
            :aria-label="`${n.pin.name} — ${n.pin.visual.label}`"
            @click="clickNode(n)"
            @mouseenter="enterNode(n)"
            @mouseleave="leaveNode"
          >
            <span
              v-if="n.pin.visual.pulse"
              class="sm-pulse absolute -inset-1.5 rounded-full"
              style="background: var(--ink-red-7)"
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
            class="group relative block rounded-full outline-none"
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
              class="relative grid size-11 place-items-center rounded-full bg-surface-gray-5 text-base font-semibold text-ink-gray-9 shadow-md transition-transform duration-150 ease-out group-active:scale-95"
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
            class="group relative block rounded-full outline-none"
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
    </TransitionGroup>

    <!-- Hover card -->
    <Transition name="smc">
      <div
        v-if="card"
        :key="card.node.key"
        data-map-card
        class="absolute z-40 rounded-xl border border-outline-gray-1 bg-surface-elevation-1 shadow-xl"
        :class="card.node.type === 'cluster' ? 'p-2' : 'p-4'"
        :style="card.style"
        @mouseenter="cancelHide"
        @mouseleave="leaveNode"
        @click.capture="cardLocked = true"
      >
        <!-- Server details: real mirror fields only. Usage metrics return here
             once Atlas reports them. -->
        <template v-if="card.node.type === 'server'">
          <div class="flex items-start gap-2">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <span class="truncate text-base font-semibold text-ink-gray-9">{{ card.node.pin.name }}</span>
                <Badge :theme="card.node.pin.visual.badgeTheme" variant="subtle" size="sm" :label="card.node.pin.visual.label" />
              </div>
              <div class="mt-0.5 truncate text-sm text-ink-gray-5">{{ card.node.pin.specs }}</div>
            </div>
            <div class="-mr-1.5 -mt-1" @click.stop>
              <slot name="card-actions" :server="card.node.pin.server" />
            </div>
          </div>
          <div class="mt-3 flex items-baseline justify-between gap-3 text-sm">
            <span class="shrink-0 font-medium text-ink-gray-8">Region</span>
            <span class="truncate text-ink-gray-9">{{ card.node.pin.flag }} {{ card.node.pin.regionLabel }}</span>
          </div>
          <div v-if="card.node.pin.publicIpv4" class="mt-2 flex items-baseline justify-between gap-3 text-sm">
            <span class="shrink-0 font-medium text-ink-gray-8">IP</span>
            <span class="truncate font-mono text-[13px] text-ink-gray-9">{{ card.node.pin.publicIpv4 }}</span>
          </div>
          <div v-if="card.node.pin.plan" class="mt-2 flex items-baseline justify-between gap-3 text-sm">
            <span class="shrink-0 font-medium text-ink-gray-8">Plan</span>
            <span class="truncate text-ink-gray-9">{{ card.node.pin.plan }}</span>
          </div>
          <div v-if="card.node.pin.frappeVersion" class="mt-2 flex items-baseline justify-between gap-3 text-sm">
            <span class="shrink-0 font-medium text-ink-gray-8">Version</span>
            <span class="truncate text-ink-gray-9">{{ card.node.pin.frappeVersion }}</span>
          </div>
        </template>

        <!-- Cluster: the servers at this spot -->
        <template v-else-if="card.node.type === 'cluster'">
          <div class="flex items-center justify-between gap-2 px-1.5 pb-1 pt-0.5">
            <span class="min-w-0 truncate text-xs font-medium text-ink-gray-5">
              {{ card.node.members[0].flag }} {{ card.node.title }} · {{ card.node.members.length }} servers
            </span>
            <button
              v-if="allowCreate"
              class="grid size-5 shrink-0 place-items-center rounded-md text-ink-gray-6 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-8 active:scale-95"
              :title="`New server in ${card.node.title}`"
              :aria-label="`New server in ${card.node.title}`"
              @click="emit('new-server', card.node.members[0].server.cluster)"
            >
              <span class="lucide-plus size-3.5" />
            </button>
          </div>
          <button
            v-for="m in card.node.members"
            :key="m.id"
            class="group flex w-full items-center gap-2.5 rounded-lg p-1.5 text-left transition-colors hover:bg-surface-gray-2"
            @click="emit('open', m.id)"
          >
            <span class="relative shrink-0">
              <ProviderAvatar :provider="m.provider" :size="28" />
              <span class="absolute -bottom-px -right-px size-2.5 rounded-full border-2 border-[var(--surface-elevation-1)]" :style="{ background: m.visual.dot }" />
            </span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-medium text-ink-gray-8">{{ m.name }}</span>
              <span class="block truncate text-xs text-ink-gray-5">{{ m.specs }}</span>
            </span>
            <span class="lucide-arrow-up-right size-3.5 shrink-0 text-ink-gray-5 opacity-0 transition-opacity group-hover:opacity-100" />
          </button>
        </template>

        <!-- Empty region: a direct path to create (markers never open cards) -->
        <template v-else-if="card.node.type === 'plus'">
          <div class="text-base font-semibold text-ink-gray-9">No servers in this region</div>
          <div class="mt-0.5 text-sm text-ink-gray-5">{{ card.node.title }}</div>
          <div class="mt-3 flex items-center gap-2">
            <span class="text-sm text-ink-gray-6">{{ card.node.targets.length > 1 ? 'Regions here' : 'Region' }}</span>
            <button
              v-for="t in card.node.targets"
              :key="t.id"
              class="block shrink-0 rounded-full transition-transform duration-150 ease-out hover:scale-110 active:scale-95"
              :title="`New server in ${t.flag} ${t.regionLabel}`"
              @click="emit('new-server', t.id)"
            >
              <ProviderAvatar :provider="t.provider" :size="20" />
            </button>
          </div>
          <Button
            class="mt-3"
            variant="subtle"
            size="sm"
            label="New server"
            icon-left="lucide-plus"
            @click="emit('new-server', card.node.targets[0].id)"
          />
        </template>
      </div>
    </Transition>

    <!-- Zoom controls; slide left when the server panel overlays the right edge -->
    <div
      v-if="interactive"
      data-map-controls
      class="sm-controls absolute bottom-14 right-4 z-30 flex flex-col overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-elevation-1 shadow-sm"
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
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch, type CSSProperties } from 'vue'
import { Badge, Button } from 'frappe-ui'
import ProviderAvatar from '@/components/servers/ProviderAvatar.vue'
import WorldDots from '@/components/servers/WorldDots.vue'
import { locationLabel, type MapPin, type MapSpot } from '@/lib/serverMap'

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
    /** Push the zoom controls left when a panel overlays the right edge (px). */
    panelOffset?: number
    /** False = no drag/wheel/dblclick/controls; the map frames itself (markers). */
    interactive?: boolean
    /** Show create affordances inside cards (page gates on server:create). */
    allowCreate?: boolean
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
  },
)

const emit = defineEmits<{
  /** A server pin (or a cluster-card row) was chosen. */
  open: [id: string]
  /** A + spot was chosen — the Atlas Instance region to create in. */
  'new-server': [region: string]
  /** A cluster was clicked; the page may narrow its list to these servers. */
  'cluster-open': [payload: { ids: string[]; label: string }]
  /** A picker marker was chosen. */
  select: [region: string]
}>()

// Same equirectangular projection as the WorldDots asset, generated on this
// exact frame — lat/lng from Atlas Instances line up with the dots.
const W = 879
const H = 443
const LAT_TOP = 83
const LAT_BOTTOM = -56
const MAX_Z = 5
const STEP = 1.7
// Past this zoom, servers sharing a spot stop counting ("3") and fan out into
// an overlapping avatar stack — whether you clicked the cluster or just
// zoomed your way in. Two zoom-in clicks (1.7² ≈ 2.89) get you there.
const STACK_Z = 2.8

function project(p: { lat: number; lng: number }): { x: number; y: number } {
  return {
    x: ((p.lng + 180) / 360) * W,
    y: ((LAT_TOP - p.lat) / (LAT_TOP - LAT_BOTTOM)) * H,
  }
}

// — Viewport: contain-fit the world, then zoom/pan on top. At zoom 1 the map
//   is centered and locked; zoomed in, it pans within the map's own bounds.
const el = ref<HTMLDivElement | null>(null)
const cw = ref(0)
const ch = ref(0)
const zoom = ref(1)
const tx = ref(0)
const ty = ref(0)
const dragging = ref(false)
const wheeling = ref(false)
const focusing = ref(false)

const base = computed(() => (cw.value && ch.value ? Math.min(cw.value / W, ch.value / H) : 0))
const k = computed(() => base.value * zoom.value)

// Transitions stay off until the first layout lands — the map must appear in
// place instantly, not zoom in from nothing.
const ready = ref(false)
watch(base, (v) => {
  if (v && !ready.value) requestAnimationFrame(() => requestAnimationFrame(() => (ready.value = true)))
})

let ro: ResizeObserver | undefined
onMounted(() => {
  ro = new ResizeObserver(([entry]) => {
    cw.value = entry.contentRect.width
    ch.value = entry.contentRect.height
  })
  if (el.value) ro.observe(el.value)
})
onBeforeUnmount(() => ro?.disconnect())

function clampPan(): void {
  const w = W * k.value
  const h = H * k.value
  tx.value = w <= cw.value ? (cw.value - w) / 2 : Math.min(0, Math.max(cw.value - w, tx.value))
  ty.value = h <= ch.value ? (ch.value - h) / 2 : Math.min(0, Math.max(ch.value - h, ty.value))
}
watch([base, cw, ch], clampPan)

const mapStyle = computed(() => ({
  transform: `translate3d(${tx.value}px, ${ty.value}px, 0) scale(${k.value})`,
}))

function zoomAt(ax: number, ay: number, factor: number): void {
  cancelFocus()
  const zNew = Math.min(MAX_Z, Math.max(1, zoom.value * factor))
  if (zNew === zoom.value) return
  const kOld = k.value
  const kNew = base.value * zNew
  tx.value = ax - ((ax - tx.value) / kOld) * kNew
  ty.value = ay - ((ay - ty.value) / kOld) * kNew
  zoom.value = zNew
  hideCard()
  clampPan()
}
function zoomStep(dir: number): void {
  zoomAt(cw.value / 2, ch.value / 2, dir > 0 ? STEP : 1 / STEP)
}

// Focus a node in one continuous move: zoom to (at least) the stack level
// while the node glides to the viewport centre. Driven frame-by-frame (CSS
// transitions off) — zoom interpolates in log space and the node's on-screen
// path is eased explicitly, so the combined motion never swings.
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
  const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)
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
function focusOn(n: MapNode): void {
  flyTo(n.x, n.y, Math.min(MAX_Z, Math.max(zoom.value, STEP * STEP)))
}

// Picker mode frames itself: fit the marker set (new provider = new frame).
// First layout lands in place; later changes glide.
function fitMarkers(): void {
  if (!base.value) return
  const pts = props.markers.map(project)
  if (!pts.length) {
    // A provider with no placed regions frames the whole world instead of
    // staying wherever the last fit left the map.
    if (!props.interactive && ready.value && zoom.value > 1) flyTo(W / 2, H / 2, 1)
    return
  }
  const pad = 48
  const xs = pts.map((p) => p.x)
  const ys = pts.map((p) => p.y)
  const bw = Math.max(...xs) - Math.min(...xs) + pad * 2
  const bh = Math.max(...ys) - Math.min(...ys) + pad * 2
  const z1 = Math.min(MAX_Z, Math.max(1, Math.min(cw.value / bw, ch.value / bh) / base.value))
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
interface DragState {
  x: number
  y: number
  tx: number
  ty: number
  id: number
  moved: boolean
}
let drag: DragState | null = null
let suppressClick = false
function closestOf(e: Event, selector: string): Element | null {
  return (e.target as Element | null)?.closest(selector) ?? null
}
function onDown(e: PointerEvent): void {
  if (e.button !== 0 || !props.interactive) return
  // A locked card (its ⋯ menu was opened) closes on any press outside it.
  if (cardLocked.value && !closestOf(e, '[data-map-card]')) hideCard()
  if (zoom.value <= 1) return
  if (closestOf(e, '[data-map-card],[data-map-controls]')) return
  drag = { x: e.clientX, y: e.clientY, tx: tx.value, ty: ty.value, id: e.pointerId, moved: false }
}
function onMove(e: PointerEvent): void {
  if (!drag) return
  const dx = e.clientX - drag.x
  const dy = e.clientY - drag.y
  if (!drag.moved && Math.hypot(dx, dy) < 4) return
  if (!drag.moved) {
    drag.moved = true
    dragging.value = true
    cancelFocus() // don't fight the user for the viewport
    hideCard()
    el.value?.setPointerCapture?.(drag.id)
  }
  tx.value = drag.tx + dx
  ty.value = drag.ty + dy
  clampPan()
}
function onUp(): void {
  if (drag?.moved) {
    suppressClick = true
    setTimeout(() => (suppressClick = false), 0)
  }
  drag = null
  dragging.value = false
}
function onDblClick(e: MouseEvent): void {
  if (!props.interactive) return
  if (closestOf(e, '[data-map-card],[data-map-controls]')) return
  if (!el.value) return
  const r = el.value.getBoundingClientRect()
  zoomAt(e.clientX - r.left, e.clientY - r.top, STEP)
}

// Trackpad: pinch (ctrl+wheel) zooms at the cursor; two-finger scroll pans
// when zoomed in. Both move without the zoom transition.
let wheelT: number | undefined
function onWheel(e: WheelEvent): void {
  if (!props.interactive) return
  const pinch = e.ctrlKey || e.metaKey
  if (!pinch && zoom.value <= 1) return
  e.preventDefault()
  wheeling.value = true
  cancelFocus()
  window.clearTimeout(wheelT)
  wheelT = window.setTimeout(() => (wheeling.value = false), 140)
  hideCard()
  if (pinch) {
    if (!el.value) return
    const r = el.value.getBoundingClientRect()
    zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.01))
  } else {
    tx.value -= e.deltaX
    ty.value -= e.deltaY
    clampPan()
  }
}

// — Nodes: greedy proximity clustering in world units, thresholds fixed in
//   screen pixels so groups split apart naturally as you zoom in.
type PlacedPin = MapPin & { wx: number; wy: number }
type PlacedSpot = MapSpot & { wx: number; wy: number }

interface ServerNode {
  type: 'server'
  key: string
  x: number
  y: number
  pin: PlacedPin
  stacked?: boolean
  stackZ?: number
}
interface ClusterNode {
  type: 'cluster'
  key: string
  x: number
  y: number
  members: PlacedPin[]
  provider: string | null
  broken: boolean
  title: string
}
interface PlusNode {
  type: 'plus'
  key: string
  x: number
  y: number
  targets: PlacedSpot[]
  title: string
}
interface MarkerNode {
  type: 'marker'
  key: string
  x: number
  y: number
  marker: PlacedSpot
  selected: boolean
}
type MapNode = ServerNode | ClusterNode | PlusNode | MarkerNode

interface Group<T> {
  x: number
  y: number
  members: T[]
}

function groupBy<T extends { wx: number; wy: number }>(items: T[], threshold: number): Group<T>[] {
  const groups: Group<T>[] = []
  for (const it of items) {
    let best: Group<T> | null = null
    let bestD = Infinity
    for (const g of groups) {
      const d = Math.hypot(g.x - it.wx, g.y - it.wy)
      if (d < threshold && d < bestD) {
        best = g
        bestD = d
      }
    }
    if (best) {
      best.members.push(it)
      best.x = best.members.reduce((s, m) => s + m.wx, 0) / best.members.length
      best.y = best.members.reduce((s, m) => s + m.wy, 0) / best.members.length
    } else {
      groups.push({ x: it.wx, y: it.wy, members: [it] })
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
  return members.reduce((a, b) => (counts[b.provider ?? ''] > counts[a.provider ?? ''] ? b : a)).provider
}

const nodes = computed<MapNode[]>(() => {
  if (!k.value) return []
  // Picker mode: every marker is its own node (a handful of regions — no
  // clustering), keyed on selection so the dot↔pin swap animates.
  if (props.markers.length) {
    return props.markers.map((m) => {
      const selected = m.id === props.selectedId
      const { wx, wy } = worldOf(m)
      return { type: 'marker' as const, key: `m-${m.id}-${selected}`, x: wx, y: wy, marker: { ...m, wx, wy }, selected }
    })
  }
  const pins: PlacedPin[] = props.pins.map((p) => ({ ...p, ...worldOf(p) }))
  const serverGroups = groupBy(pins, 46 / k.value)
  const out: MapNode[] = []
  for (const g of serverGroups) {
    if (g.members.length === 1) {
      out.push({ type: 'server', key: `s-${g.members[0].id}`, x: g.x, y: g.y, pin: g.members[0] })
    } else if (zoom.value >= STACK_Z) {
      const gap = 24 / k.value
      g.members.forEach((m, i) => {
        out.push({
          type: 'server',
          key: `s-${m.id}`,
          x: g.x + (i - (g.members.length - 1) / 2) * gap,
          y: g.y,
          pin: m,
          stacked: true,
          stackZ: g.members.length - i,
        })
      })
    } else {
      out.push({
        type: 'cluster',
        key: `c-${g.members.map((m) => m.id).sort().join('.')}`,
        x: g.x,
        y: g.y,
        members: g.members,
        provider: dominantProvider(g.members),
        broken: g.members.some((m) => m.visual.pulse),
        title: locationLabel(g.members.map((m) => m.regionLabel)),
      })
    }
  }
  // Empty regions collapse into one + per spot. A region sitting under a
  // server node is dropped individually, so its neighbours still show.
  const spots: PlacedSpot[] = props.spots
    .map((s) => ({ ...s, ...worldOf(s) }))
    .filter((s) => !serverGroups.some((sg) => Math.hypot(sg.x - s.wx, sg.y - s.wy) < 36 / k.value))
  for (const g of groupBy(spots, 30 / k.value)) {
    out.push({
      type: 'plus',
      key: `p-${g.members.map((s) => s.id).sort().join('.')}`,
      x: g.x,
      y: g.y,
      targets: g.members,
      title: locationLabel(g.members.map((s) => s.regionLabel)),
    })
  }
  return out
})

function worldOf(p: { lat: number; lng: number }): { wx: number; wy: number } {
  const { x, y } = project(p)
  return { wx: x, wy: y }
}

function screenOf(n: { x: number; y: number }): { sx: number; sy: number } {
  return { sx: tx.value + n.x * k.value, sy: ty.value + n.y * k.value }
}

const highlightKey = computed(() => {
  if (!props.highlightId) return null
  const n = nodes.value.find(
    (node) =>
      (node.type === 'server' && node.pin.id === props.highlightId) ||
      (node.type === 'cluster' && node.members.some((m) => m.id === props.highlightId)) ||
      (node.type === 'marker' && node.marker.id === props.highlightId),
  )
  return n?.key || null
})

function isHot(n: MapNode): boolean {
  return n.key === hoverKey.value || n.key === highlightKey.value
}

function posStyle(n: MapNode): CSSProperties {
  const zBase = n.type === 'marker' ? (n.selected ? 21 : 12) : n.type === 'plus' ? 10 : n.type === 'cluster' ? 21 : 20
  const { sx, sy } = screenOf(n)
  return {
    transform: `translate3d(${sx}px, ${sy}px, 0)`,
    zIndex: isHot(n) ? 30 : zBase + (n.type === 'server' ? n.stackZ || 0 : 0),
  }
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
  if (dragging.value || cardLocked.value) return
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
  const node = hoverKey.value ? nodes.value.find((n) => n.key === hoverKey.value) : undefined
  if (!node) return null
  const { sx, sy } = screenOf(node)
  const width = node.type === 'server' ? 320 : 288
  // The side panel overlays the map's right edge, so the card clamps to the
  // uncovered width — same treatment as the zoom controls.
  const visibleW = cw.value - props.panelOffset
  // Stacked avatars overlap sideways, so their card drops below instead of
  // covering the neighbours to the right.
  if (node.type === 'server' && node.stacked) {
    const left = Math.min(Math.max(sx - width / 2, 12), Math.max(12, visibleW - width - 12))
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
  const estH = node.type === 'server' ? 220 : node.type === 'cluster' ? 40 + node.members.length * 48 : 160
  const top = Math.min(Math.max(sy - 36, 12), Math.max(12, ch.value - estH - 12))
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

// Let the page focus the map from the side panel: glide to the node that
// holds this server (its own pin, or the cluster it's grouped into).
function focusPin(id: string): void {
  const n = nodes.value.find(
    (node) =>
      (node.type === 'server' && node.pin.id === id) ||
      (node.type === 'cluster' && node.members.some((m) => m.id === id)),
  )
  if (n) focusOn(n)
}
defineExpose({ focusPin })

function clickNode(n: MapNode): void {
  if (suppressClick) return
  if (n.type === 'marker') {
    emit('select', n.marker.id)
  } else if (n.type === 'server') {
    // No per-server page exists (yet) — the card is the detail surface, so a
    // click pins it open with its actions menu reachable.
    window.clearTimeout(showT)
    hoverKey.value = n.key
    cardLocked.value = true
    emit('open', n.pin.id)
  } else if (n.type === 'plus') {
    emit('new-server', n.targets[0].id)
  } else {
    // A cluster focuses the map on itself, zooming to the stack level. The
    // page narrows the list to this spot if the panel happens to be open.
    focusOn(n)
    emit('cluster-open', { ids: n.members.map((m) => m.id), label: n.title })
  }
}
</script>

<style scoped>
/* The map layer and every node share one curve, so pins track the dots
   through the whole zoom. Transitions only arm after the first layout (the
   map must appear in place, not animate in); dragging and pinching switch
   back to direct updates. */
.sm-pos {
  will-change: transform;
}
.sm-anim .sm-pos {
  transition: transform 450ms cubic-bezier(0.77, 0, 0.175, 1);
}
.sm-drag .sm-pos {
  transition: none;
}
.sm-center {
  transform: translate(-50%, -50%);
  transition: transform 250ms cubic-bezier(0.23, 1, 0.32, 1), opacity 200ms ease-out;
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
  transition: opacity 150ms cubic-bezier(0.23, 1, 0.32, 1), transform 150ms cubic-bezier(0.23, 1, 0.32, 1);
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

.sm-controls {
  transition: transform 300ms cubic-bezier(0.32, 0.72, 0, 1);
}

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
  .sm-center,
  .sm-controls {
    transition: none;
  }
  .sm-pulse {
    animation: none;
    opacity: 0.2;
  }
}
</style>
