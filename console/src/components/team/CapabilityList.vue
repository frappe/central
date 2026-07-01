<script setup lang="ts">
import { computed } from 'vue'
import { groupCapabilitiesByPlane } from '@/lib/capabilities'
import type { CapabilityInfo } from '@/types/api'

// Renders a set of granted capabilities grouped by plane, each with its human
// description — the "what this role allows" transparency panel shown in the right
// sidebar for a member's role or a role's definition. Capabilities not in `caps`
// are omitted; pass the full palette so names resolve to descriptions.
const props = withDefaults(defineProps<{
  caps: string[]
  palette: CapabilityInfo[]
}>(), {
  caps: () => [],
  palette: () => [],
})

const groups = computed(() => groupCapabilitiesByPlane(props.palette, props.caps))
</script>

<template>
  <div v-if="caps.length" class="space-y-4">
    <section v-for="group in groups" :key="group.plane">
      <h4 class="mb-2 text-xs font-medium uppercase tracking-wide text-ink-gray-4">
        {{ group.label }}
      </h4>
      <ul class="space-y-2">
        <li v-for="cap in group.caps" :key="cap.name" class="flex gap-2">
          <svg class="mt-0.5 h-4 w-4 shrink-0 text-ink-green-6" viewBox="0 0 16 16" fill="none">
            <path d="M3.5 8.5l3 3 6-7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <div class="min-w-0">
            <p class="font-mono text-xs text-ink-gray-7">{{ cap.name }}</p>
            <p class="text-p-sm text-ink-gray-5">{{ cap.description }}</p>
          </div>
        </li>
      </ul>
    </section>
  </div>
  <p v-else class="text-p-sm text-ink-gray-4">This role grants no capabilities.</p>
</template>
