<script setup lang="ts">
import { computed } from 'vue'
import mapUrl from '@/assets/dotted-map.svg'
import type { RegionInfo } from '@/lib/regions'

const props = defineProps<{ region: RegionInfo; ready?: boolean }>()

const ZOOM = 3.8
const MAP_ASPECT = 238 / 120 // dotted-map.svg viewBox
const CARD_ASPECT = 2
// The dot rests slightly below card center so the label pill has headroom.
const DOT = { x: 50, y: 56 }

const imageStyle = computed(() => {
  const width = ZOOM * 100
  const height = (width / MAP_ASPECT) * CARD_ASPECT
  return {
    width: `${width}%`,
    left: `${DOT.x - props.region.x * width}%`,
    top: `${DOT.y - props.region.y * height}%`,
  }
})
</script>

<template>
  <div class="relative aspect-[2/1] w-full overflow-hidden rounded-2xl border border-outline-gray-1 bg-surface-white">
    <img :src="mapUrl" alt="" class="absolute max-w-none" :style="imageStyle" />
    <div class="absolute" :style="{ left: `${DOT.x}%`, top: `${DOT.y}%` }">
      <span
        v-if="!ready"
        class="region-ping absolute block size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-gray-900"
      />
      <span
        class="absolute block size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full transition-colors duration-500"
        :class="ready ? 'bg-green-600 ring-4 ring-green-600/15' : 'bg-gray-900 ring-4 ring-gray-900/10'"
      />
      <div
        class="absolute bottom-2.5 -translate-x-1/2 whitespace-nowrap rounded-full bg-white px-2.5 py-1 text-xs font-medium text-ink-gray-7 shadow-md"
      >
        {{ region.label }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.region-ping {
  animation: region-ping 2.4s cubic-bezier(0.23, 1, 0.32, 1) infinite;
}

@keyframes region-ping {
  0% {
    transform: translate(-50%, -50%) scale(1);
    opacity: 0.3;
  }
  75%,
  100% {
    transform: translate(-50%, -50%) scale(3);
    opacity: 0;
  }
}
</style>
