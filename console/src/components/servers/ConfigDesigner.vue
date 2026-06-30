<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  clamp,
  estimateConfig,
  maxAffordableDisk,
  maxAffordableVcpu,
  ramFor,
} from '@/lib/composed'
import type { ComposedConfig, Profile, RateCard } from '@/types/api'

// Design-your-own config controls (#84). Drag Compute (vCPU snaps to the profile's
// steps); RAM follows automatically by the profile's ratio, shown as a derived pill
// — never independently chosen, so an off-ratio shape can't be expressed. Storage is
// an independent bounded slider with ± steppers. Both have a hard stop at `available`
// headroom, so the customer can't drag into a config they can't afford. The price is
// shown by the parent; the server re-validates everything at provision (#83).
const props = defineProps<{
  profiles: Profile[]
  rateCard: RateCard
  available: number
  // Pre-fill the controls with a running config's shape (resize, #82/#84).
  initial?: ComposedConfig | null
}>()

// The chosen config (null while invalid / over headroom) — the parent provisions it.
const config = defineModel<ComposedConfig | null>({ required: true })

const DISK_STEP = 10

const profileName = ref<string>(props.initial?.sub_category ?? props.profiles[0]?.sub_category ?? '')
const profile = computed<Profile | null>(
  () => props.profiles.find((p) => p.sub_category === profileName.value) ?? null,
)

const steps = computed<number[]>(() => [...(profile.value?.vcpu_steps ?? [])].sort((a, b) => a - b))
const seededIndex = props.initial ? steps.value.indexOf(props.initial.vcpus) : -1
const vcpuIndex = ref(seededIndex < 0 ? 0 : seededIndex)
const vcpus = computed<number>(() => steps.value[vcpuIndex.value] ?? steps.value[0] ?? 0)
const diskGb = ref<number>(props.initial?.disk_gb ?? profile.value?.disk_min ?? 0)

const ram = computed<number>(() => (profile.value ? ramFor(vcpus.value, profile.value) : 0))

// Hard stops: the largest vCPU step / disk that still fit the remaining headroom,
// each given the other's current value.
const maxVcpuIndex = computed<number>(() => {
  if (!profile.value) return 0
  const i = steps.value.indexOf(maxAffordableVcpu(profile.value, props.rateCard, props.available, diskGb.value))
  return i < 0 ? 0 : i
})
const maxDisk = computed<number>(() =>
  profile.value ? maxAffordableDisk(profile.value, props.rateCard, props.available, vcpus.value) : 0,
)

const overHeadroom = computed<boolean>(() =>
  profile.value
    ? estimateConfig(
        { sub_category: profileName.value, vcpus: vcpus.value, memory_gb: ram.value, disk_gb: diskGb.value },
        props.rateCard,
      ) > props.available
    : false,
)

function stepDisk(delta: number) {
  if (!profile.value) return
  diskGb.value = clamp(diskGb.value + delta * DISK_STEP, profile.value.disk_min, maxDisk.value)
}

// Reset to the profile's floor whenever the profile changes (not on first mount).
watch(profile, (p) => {
  vcpuIndex.value = 0
  diskGb.value = p?.disk_min ?? 0
})

// Keep both controls inside the live hard stops (clamp down only, so this converges).
watch([maxVcpuIndex, maxDisk], () => {
  if (vcpuIndex.value > maxVcpuIndex.value) vcpuIndex.value = maxVcpuIndex.value
  if (diskGb.value > maxDisk.value) diskGb.value = maxDisk.value
})

// Publish the chosen config to the parent — null while there's no priceable,
// in-headroom shape (the submit button stays disabled).
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
        <span class="shrink-0 rounded-md bg-surface-gray-2 px-3 py-1.5 text-p-sm font-medium text-ink-gray-8">
          {{ vcpus }} vCPU
        </span>
        <span class="shrink-0 rounded-md bg-surface-gray-2 px-3 py-1.5 text-p-sm font-medium text-ink-gray-8">
          {{ ram }} GB RAM
        </span>
      </div>

      <!-- Storage: independent bounded slider with ± steppers. -->
      <div class="flex items-center gap-4">
        <span class="w-20 shrink-0 text-p-sm text-ink-gray-7">Storage</span>
        <input
          v-model.number="diskGb"
          type="range"
          :min="profile.disk_min"
          :max="Math.max(profile.disk_min, maxDisk)"
          :step="DISK_STEP"
          class="min-w-0 flex-1 accent-ink-gray-9"
          aria-label="Storage (GB)"
        />
        <button
          type="button"
          class="shrink-0 rounded-md bg-surface-gray-2 px-3 py-1.5 text-ink-gray-7 hover:bg-surface-gray-3 disabled:opacity-50"
          :disabled="diskGb <= profile.disk_min"
          aria-label="Less storage"
          @click="stepDisk(-1)"
        >
          <span class="lucide-minus size-4" aria-hidden="true" />
        </button>
        <span class="shrink-0 rounded-md bg-surface-gray-2 px-3 py-1.5 text-p-sm font-medium text-ink-gray-8">
          {{ diskGb }} GB
        </span>
        <button
          type="button"
          class="shrink-0 rounded-md bg-surface-gray-2 px-3 py-1.5 text-ink-gray-7 hover:bg-surface-gray-3 disabled:opacity-50"
          :disabled="diskGb >= maxDisk"
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
