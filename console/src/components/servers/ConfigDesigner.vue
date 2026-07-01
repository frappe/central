<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import LadderSelect from '@/components/servers/LadderSelect.vue'
import {
  clamp,
  estimateConfig,
  formatGb,
  formatVcpu,
  maxAffordableDisk,
  maxAffordableVcpu,
  ramFor,
} from '@/lib/composed'
import type { ComposedConfig, Profile, RateCard } from '@/types/api'

// Design-your-own config controls (#84). Compute and Storage are both discrete
// ladders the slider snaps to (vCPU from the configurator's set incl. fractions;
// storage from its own ladder). RAM follows Compute automatically by the profile's
// ratio, shown as a derived pill — never independently chosen, so an off-ratio shape
// can't be expressed. Both sliders have a hard stop at `available` headroom. The
// price is shown by the parent; the server re-validates everything at provision (#83).
const props = defineProps<{
  profiles: Profile[]
  rateCard: RateCard
  available: number
  // Pre-fill the controls with a running config's shape (resize, #82/#84).
  initial?: ComposedConfig | null
}>()

// The chosen config (null while invalid / over headroom) — the parent provisions it.
const config = defineModel<ComposedConfig | null>({ required: true })

const profileName = ref<string>(props.initial?.sub_category ?? props.profiles[0]?.sub_category ?? '')
const profile = computed<Profile | null>(
  () => props.profiles.find((p) => p.sub_category === profileName.value) ?? null,
)

const vcpuSteps = computed<number[]>(() => [...(profile.value?.vcpu_steps ?? [])].sort((a, b) => a - b))
const diskSteps = computed<number[]>(() => [...(profile.value?.disk_steps ?? [])].sort((a, b) => a - b))

// Both sliders are index-based over their ladder, so dragging always lands on a rung.
const vcpuIndex = ref(seedIndex(vcpuSteps.value, props.initial?.vcpus))
const diskIndex = ref(seedIndex(diskSteps.value, props.initial?.disk_gb))
const vcpus = computed<number>(() => vcpuSteps.value[vcpuIndex.value] ?? vcpuSteps.value[0] ?? 0)
const diskGb = computed<number>(() => diskSteps.value[diskIndex.value] ?? diskSteps.value[0] ?? 0)
const ram = computed<number>(() => (profile.value ? ramFor(vcpus.value, profile.value) : 0))

// Hard stops: the largest vCPU / storage rung that still fits the remaining
// headroom, each given the other's current value.
const maxVcpuIndex = computed<number>(() =>
  profile.value
    ? indexOf(vcpuSteps.value, maxAffordableVcpu(profile.value, props.rateCard, props.available, diskGb.value))
    : 0,
)
const maxDiskIndex = computed<number>(() =>
  profile.value
    ? indexOf(diskSteps.value, maxAffordableDisk(profile.value, props.rateCard, props.available, vcpus.value))
    : 0,
)

// Dropdown ladders (the precise-pick companion to the sliders). Rungs past the
// headroom hard stop are disabled. RAM is keyed by its vCPU rung, so picking a RAM
// value just picks the matching vCPU — it can't express an off-ratio shape.
const vcpuOptions = computed(() =>
  vcpuSteps.value.map((v, i) => ({ label: `${formatVcpu(v)} vCPU`, value: v, disabled: i > maxVcpuIndex.value })),
)
const ramOptions = computed(() =>
  profile.value
    ? vcpuSteps.value.map((v, i) => ({
        label: `${formatGb(ramFor(v, profile.value!))} GB RAM`,
        value: v,
        disabled: i > maxVcpuIndex.value,
      }))
    : [],
)
// The storage unit is driven from the Disk resource's unit on the rate card (#89),
// single-sourced rather than a hardcoded "GB"; falls back to 'GB' until it loads.
const diskUnit = computed<string>(() => props.rateCard.Disk?.unit ?? 'GB')
const diskOptions = computed(() =>
  diskSteps.value.map((d, i) => ({
    label: `${formatGb(d)} ${diskUnit.value}`,
    value: d,
    disabled: i > maxDiskIndex.value,
  })),
)

function setVcpu(v: number) {
  vcpuIndex.value = indexOf(vcpuSteps.value, v)
}
function setDisk(d: number) {
  diskIndex.value = indexOf(diskSteps.value, d)
}

const overHeadroom = computed<boolean>(() =>
  profile.value
    ? estimateConfig(
        { sub_category: profileName.value, vcpus: vcpus.value, memory_gb: ram.value, disk_gb: diskGb.value },
        props.rateCard,
      ) > props.available
    : false,
)

function stepDisk(delta: number) {
  diskIndex.value = clamp(diskIndex.value + delta, 0, maxDiskIndex.value)
}

// Reset to each ladder's floor when the profile changes (not on first mount).
watch(profile, () => {
  vcpuIndex.value = 0
  diskIndex.value = 0
})

// Keep both sliders inside the live hard stops (clamp down only, so this converges).
watch([maxVcpuIndex, maxDiskIndex], () => {
  if (vcpuIndex.value > maxVcpuIndex.value) vcpuIndex.value = maxVcpuIndex.value
  if (diskIndex.value > maxDiskIndex.value) diskIndex.value = maxDiskIndex.value
})

// Publish the chosen config — null while there's no priceable, in-headroom shape.
watch(
  [profile, vcpus, ram, diskGb, overHeadroom],
  () => {
    config.value =
      profile.value && !overHeadroom.value
        ? { sub_category: profileName.value, vcpus: vcpus.value, memory_gb: ram.value, disk_gb: diskGb.value }
        : null
  },
  { immediate: true },
)

function seedIndex(ladder: number[], value: number | undefined): number {
  const i = value === undefined ? -1 : ladder.indexOf(value)
  return i < 0 ? 0 : i
}
function indexOf(ladder: number[], value: number): number {
  const i = ladder.indexOf(value)
  return i < 0 ? 0 : i
}
</script>

<template>
  <div class="space-y-4">
    <!-- Optimisation profile — only when the region offers more than one. -->
    <div v-if="profiles.length > 1" class="flex flex-wrap gap-2">
      <button
        v-for="p in profiles"
        :key="p.sub_category"
        type="button"
        class="rounded-md border px-2.5 py-1 text-p-xs transition-colors"
        :class="
          profileName === p.sub_category
            ? 'border-outline-gray-4 bg-surface-gray-2 text-ink-gray-9'
            : 'border-outline-gray-2 text-ink-gray-6 hover:border-outline-gray-3'
        "
        @click="profileName = p.sub_category"
      >
        {{ p.sub_category }}
      </button>
    </div>

    <template v-if="profile">
      <!-- Compute: vCPU slider with the derived RAM shown as a pill. -->
      <div class="flex items-center gap-4">
        <span class="w-20 shrink-0 text-p-sm text-ink-gray-7">Compute</span>
        <input
          v-model.number="vcpuIndex"
          type="range"
          min="0"
          :max="Math.max(0, maxVcpuIndex)"
          step="1"
          class="min-w-0 flex-1 accent-ink-gray-9"
          aria-label="vCPU"
        />
        <LadderSelect class="shrink-0" :options="vcpuOptions" :selected="vcpus" @select="setVcpu" />
        <LadderSelect class="shrink-0" :options="ramOptions" :selected="vcpus" @select="setVcpu" />
      </div>

      <!-- Storage: independent ladder slider with rung-by-rung ± steppers. -->
      <div class="flex items-center gap-4">
        <span class="w-20 shrink-0 text-p-sm text-ink-gray-7">Storage</span>
        <input
          v-model.number="diskIndex"
          type="range"
          min="0"
          :max="Math.max(0, maxDiskIndex)"
          step="1"
          class="min-w-0 flex-1 accent-ink-gray-9"
          aria-label="Storage"
        />
        <button
          type="button"
          class="shrink-0 rounded-md bg-surface-gray-2 px-3 py-1.5 text-ink-gray-7 hover:bg-surface-gray-3 disabled:opacity-50"
          :disabled="diskIndex <= 0"
          aria-label="Less storage"
          @click="stepDisk(-1)"
        >
          <span class="lucide-minus size-4" aria-hidden="true" />
        </button>
        <LadderSelect class="shrink-0" :options="diskOptions" :selected="diskGb" @select="setDisk" />
        <button
          type="button"
          class="shrink-0 rounded-md bg-surface-gray-2 px-3 py-1.5 text-ink-gray-7 hover:bg-surface-gray-3 disabled:opacity-50"
          :disabled="diskIndex >= maxDiskIndex"
          aria-label="More storage"
          @click="stepDisk(1)"
        >
          <span class="lucide-plus size-4" aria-hidden="true" />
        </button>
      </div>

      <p v-if="overHeadroom" class="text-p-xs text-ink-red-5">
        This config is over your remaining spending limit.
      </p>
    </template>
  </div>
</template>
