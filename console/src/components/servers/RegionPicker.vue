<template>
  <!-- Provider → region cascade for the Change Plan dialog. Staying in the current
       region is a plain plan change; leaving it flips the flow into a migration —
       the badge telegraphs that before the footer button changes. -->
  <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
    <div>
      <div class="mb-1.5 flex items-center justify-between">
        <label class="block text-xs text-ink-gray-5">Provider</label>
        <Badge v-if="providerIsCurrent" label="Current" theme="gray" variant="subtle" size="sm" />
        <Badge v-else label="Migration required" theme="blue" variant="subtle" size="sm" />
      </div>
      <FormControl
        type="select"
        :model-value="providerId"
        :options="providerOptions"
        aria-label="Provider"
        @update:model-value="selectProvider"
      />
    </div>

    <div>
      <div class="mb-1.5 flex items-center justify-between">
        <label class="block text-xs text-ink-gray-5">Region</label>
        <Badge v-if="model === currentRegion" label="Current" theme="gray" variant="subtle" size="sm" />
        <Badge v-else label="Migration required" theme="blue" variant="subtle" size="sm" />
      </div>
      <FormControl
        type="select"
        :model-value="model"
        :options="regionOptions"
        aria-label="Region"
        @update:model-value="(v: string) => (model = v)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Badge, FormControl } from 'frappe-ui'
import { flagEmoji, regionLabel } from '@/lib/serverMap'
import type { Region } from '@/types/Region'

const props = defineProps<{
  regions: Region[]
  /** The server's home region — gets the "Current" badge. */
  currentRegion: string
}>()

const model = defineModel<string>({ required: true })

const UNBRANDED = 'Other'
const providerOf = (r: Region) => r.provider || UNBRANDED
const regionById = (id: string) => props.regions.find((r) => r.region === id)

// The picked region drives the provider; changing provider snaps to its first region.
const providerId = ref(providerOf(regionById(model.value) ?? props.regions[0] ?? ({} as Region)))
watch(model, (id) => {
  const region = regionById(id)
  if (region) providerId.value = providerOf(region)
})

const providerOptions = computed(() =>
  [...new Set(props.regions.map(providerOf))].map((p) => ({ label: p, value: p })),
)

const regionOptions = computed(() =>
  props.regions
    .filter((r) => providerOf(r) === providerId.value)
    .map((r) => ({ label: `${flagEmoji(r.country_code)} ${regionLabel(r)}`.trim(), value: r.region })),
)

const providerIsCurrent = computed(() => {
  const current = regionById(props.currentRegion)
  return !!current && providerOf(current) === providerId.value
})

function selectProvider(p: string): void {
  providerId.value = p
  const first = props.regions.find((r) => providerOf(r) === p)
  if (first && providerOf(regionById(model.value) ?? ({} as Region)) !== p) model.value = first.region
}
</script>
