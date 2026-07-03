<template>
  <!-- The review-step hero: from → to on the dotted world, endpoint cards pinned
       over it, new cost bottom-right. Static — no pan/zoom — so it stays a light
       sibling of ServerMap sharing the same projection and WorldDots art. -->
  <div class="relative h-72 overflow-hidden rounded-2xl border border-outline-gray-3 bg-surface-base">
    <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="xMidYMid meet" class="h-full w-full">
      <g :style="zoomStyle">
        <WorldDots class="text-ink-gray-3" :style="{ width: `${W}px`, height: `${H}px` }" />

        <!-- Flight-route arc: dotted base + green overlay (fills with progress). -->
        <g v-if="arc">
          <path
            :d="arc"
            fill="none"
            stroke="var(--ink-gray-6)"
            stroke-width="1.5"
            stroke-dasharray="6 5"
            stroke-linecap="round"
            opacity="0.9"
            vector-effect="non-scaling-stroke"
          />
          <path
            :d="arc"
            fill="none"
            stroke="var(--ink-green-7)"
            stroke-width="2.5"
            pathLength="1"
            :stroke-dasharray="`${progress} 1`"
            stroke-linecap="round"
            vector-effect="non-scaling-stroke"
          />
        </g>

        <!-- Endpoints counter-scale by 1/s so their on-screen size holds at any zoom. -->
        <g v-for="p in endpoints" :key="p.key" :style="p.posStyle">
          <circle v-if="p.pulse" cx="0" cy="0" r="11" fill="var(--ink-green-7)" class="mm-pulse" />
          <circle cx="0" cy="0" r="5" :fill="p.color" />
        </g>
      </g>
    </svg>

    <!-- From — top left -->
    <div class="mm-card absolute left-3 top-3 w-52 rounded-xl border border-outline-gray-2 bg-surface-elevation-1/85 p-2.5 shadow-sm backdrop-blur-md" :class="{ 'is-in': shown }">
      <div class="text-xs text-ink-gray-5">From</div>
      <div class="mt-1 flex items-center gap-2">
        <ProviderAvatar :provider="from.provider" :size="22" />
        <div class="min-w-0">
          <div class="truncate text-sm font-medium text-ink-gray-9">
            {{ flagEmoji(from.country_code) }} {{ regionLabel(from) }}
          </div>
          <div v-if="fromPlan" class="truncate text-xs text-ink-gray-5">{{ fromPlan }}</div>
        </div>
      </div>
    </div>

    <!-- To — top right -->
    <div class="mm-card absolute right-3 top-3 w-52 rounded-xl border border-outline-gray-2 bg-surface-elevation-1/85 p-2.5 shadow-sm backdrop-blur-md" :class="{ 'is-in': shown }" style="transition-delay: 70ms">
      <div class="text-xs text-ink-gray-5">To</div>
      <div class="mt-1 flex items-center gap-2">
        <ProviderAvatar :provider="to.provider" :size="22" />
        <div class="min-w-0">
          <div class="truncate text-sm font-medium text-ink-gray-9">
            {{ flagEmoji(to.country_code) }} {{ regionLabel(to) }}
          </div>
          <div v-if="toPlan" class="truncate text-xs text-ink-gray-5">{{ toPlan }}</div>
        </div>
      </div>
    </div>

    <!-- New cost — bottom right -->
    <div v-if="cost" class="mm-card absolute bottom-3 right-3 rounded-lg border border-outline-gray-2 bg-surface-elevation-1/85 px-3 py-1.5 text-right shadow-sm backdrop-blur-md" :class="{ 'is-in': shown }" style="transition-delay: 140ms">
      <div class="text-[10px] uppercase tracking-wide text-ink-gray-5">New cost</div>
      <div class="text-sm font-bold tabular-nums text-ink-gray-9">
        {{ cost }}<span class="text-xs font-normal text-ink-gray-5">/mo</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import WorldDots from '@/components/servers/WorldDots.vue'
import ProviderAvatar from '@/components/servers/ProviderAvatar.vue'
import { flagEmoji, hasMapCoords, regionLabel } from '@/lib/serverMap'
import type { Region } from '@/types/Region'

const props = withDefaults(
  defineProps<{
    from: Region
    to: Region
    fromPlan?: string
    toPlan?: string
    /** Already formatted, e.g. "₹3,400". */
    cost?: string
    /** Arc fill 0–1 (a progress view sets this; the review leaves it 0). */
    progress?: number
  }>(),
  { fromPlan: '', toPlan: '', cost: '', progress: 0 },
)

// Same projection constants as ServerMap/WorldDots.
const W = 879
const H = 443
const LAT_TOP = 83
const LAT_BOTTOM = -56

interface Point {
  x: number
  y: number
}

function project(latitude: number, longitude: number): Point {
  return {
    x: ((longitude + 180) / 360) * W,
    y: ((LAT_TOP - latitude) / (LAT_TOP - LAT_BOTTOM)) * H,
  }
}

// A region seeded without coordinates can't be pinned — fall back to the whole
// world with the overlay cards still telling the story.
const points = computed<{ from: Point | null; to: Point | null }>(() => ({
  from: hasMapCoords(props.from) ? project(props.from.latitude!, props.from.longitude!) : null,
  to: hasMapCoords(props.to) ? project(props.to.latitude!, props.to.longitude!) : null,
}))

// Frame both endpoints with generous padding, preserving the map's aspect.
const box = computed(() => {
  const pts = [points.value.from, points.value.to].filter((p): p is Point => !!p)
  if (!pts.length) return { x: 0, y: 0, w: W, h: H }
  const pad = 80
  const xs = pts.map((p) => p.x)
  const ys = pts.map((p) => p.y)
  let x = Math.min(...xs) - pad
  let y = Math.min(...ys) - pad
  let w = Math.max(...xs) - Math.min(...xs) + pad * 2
  let h = Math.max(...ys) - Math.min(...ys) + pad * 2
  const aspect = W / H
  if (w / h < aspect) {
    const nw = h * aspect
    x -= (nw - w) / 2
    w = nw
  } else {
    const nh = w / aspect
    y -= (nh - h) / 2
    h = nh
  }
  return { x, y, w, h }
})

const s = computed(() => Math.min(W / box.value.w, H / box.value.h))

const zoomStyle = computed(() => {
  const b = box.value
  const scale = s.value
  return {
    transform: `translate(${(W - b.w * scale) / 2 - b.x * scale}px, ${(H - b.h * scale) / 2 - b.y * scale}px) scale(${scale})`,
    transformOrigin: '0 0',
  }
})

const endpoints = computed(() => {
  const inv = 1 / s.value
  const make = (key: string, p: Point | null, color: string, pulse: boolean) =>
    p && {
      key,
      color,
      pulse,
      posStyle: { transform: `translate(${p.x}px, ${p.y}px) scale(${inv})`, transformOrigin: '0 0' },
    }
  return [
    make('from', points.value.from, 'var(--ink-gray-9)', false),
    make('to', points.value.to, 'var(--ink-green-7)', true),
  ].filter((p): p is NonNullable<typeof p> => !!p)
})

// The arc bows upward like a flight route: control-point pull grows with √distance.
const arc = computed(() => {
  const a = points.value.from
  const b = points.value.to
  if (!a || !b) return ''
  const dx = b.x - a.x
  const dy = b.y - a.y
  const len = Math.hypot(dx, dy) || 1
  let px = -dy / len
  let py = dx / len
  if (py > 0) {
    px = -px
    py = -py
  }
  const offset = Math.min(Math.max(Math.sqrt(len) * 3.2, 16), 130)
  return `M ${a.x} ${a.y} Q ${(a.x + b.x) / 2 + px * offset} ${(a.y + b.y) / 2 + py * offset} ${b.x} ${b.y}`
})

const progress = computed(() => Math.max(0, Math.min(1, props.progress)))

const shown = ref(false)
onMounted(() => nextTick(() => (shown.value = true)))
</script>

<style scoped>
.mm-card {
  opacity: 0;
  transform: translateY(6px);
  transition:
    opacity 0.24s cubic-bezier(0.23, 1, 0.32, 1),
    transform 0.24s cubic-bezier(0.23, 1, 0.32, 1);
}
.mm-card.is-in {
  opacity: 1;
  transform: translateY(0);
}
.mm-pulse {
  animation: mm-pulse 1.8s ease-in-out infinite;
}
@keyframes mm-pulse {
  0%,
  100% {
    opacity: 0.32;
  }
  50% {
    opacity: 0.1;
  }
}
@media (prefers-reduced-motion: reduce) {
  .mm-card {
    transform: none;
    transition: opacity 0.2s ease;
  }
  .mm-card.is-in {
    transform: none;
  }
  .mm-pulse {
    animation: none;
    opacity: 0.2;
  }
}
</style>
