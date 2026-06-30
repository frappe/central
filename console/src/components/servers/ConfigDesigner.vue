<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { formatMoney } from '@/lib/plans'
import {
  configSpecs,
  estimateConfig,
  maxAffordableDisk,
  maxAffordableVcpu,
  ramFor,
} from '@/lib/composed'
import type { ComposedConfig, Profile, RateCard } from '@/types/api'

// Design-your-own config slider (#84). Pick an optimisation profile, drag vCPU
// (snaps to the profile's steps); RAM follows automatically by the profile's ratio
// (not independently draggable, so an off-ratio shape can't be expressed); disk is
// an independent bounded slider. The estimate recomputes live and both sliders have
// a hard stop at `available` headroom — the customer can't drag into a config they
// can't afford. The server re-validates everything at provision (#83).
const props = defineProps<{
  profiles: Profile[]
  rateCard: RateCard
  available: number
  currency: string
}>()

// The chosen config (null while invalid / over headroom) — the parent provisions it.
const config = defineModel<ComposedConfig | null>({ required: true })

const profileName = ref<string>(props.profiles[0]?.sub_category ?? '')
const profile = computed<Profile | null>(
  () => props.profiles.find((p) => p.sub_category === profileName.value) ?? null,
)

const steps = computed<number[]>(() => [...(profile.value?.vcpu_steps ?? [])].sort((a, b) => a - b))
const vcpuIndex = ref(0)
const vcpus = computed<number>(() => steps.value[vcpuIndex.value] ?? steps.value[0] ?? 0)
const diskGb = ref<number>(profile.value?.disk_min ?? 0)

const ram = computed<number>(() => (profile.value ? ramFor(vcpus.value, profile.value) : 0))

// Hard stops: the largest vCPU step / disk that still fit the remaining headroom,
// each given the other's current value.
const maxVcpu = computed<number>(() =>
  profile.value ? maxAffordableVcpu(profile.value, props.rateCard, props.available, diskGb.value) : 0,
)
const maxVcpuIndex = computed<number>(() => {
  const i = steps.value.indexOf(maxVcpu.value)
  return i < 0 ? 0 : i
})
const maxDisk = computed<number>(() =>
  profile.value ? maxAffordableDisk(profile.value, props.rateCard, props.available, vcpus.value) : 0,
)

const estimate = computed<number>(() =>
  profile.value
    ? estimateConfig(
        { sub_category: profileName.value, vcpus: vcpus.value, memory_gb: ram.value, disk_gb: diskGb.value },
        props.rateCard,
      )
    : 0,
)
const overHeadroom = computed<boolean>(() => estimate.value > props.available)

// Reset the sliders to the profile's floor whenever the profile changes.
watch(profile, (p) => {
  vcpuIndex.value = 0
  diskGb.value = p?.disk_min ?? 0
})

// Keep both sliders inside the live hard stops (clamp down only, so this converges).
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
  <div class="space-y-6">
    <!-- Optimisation profile -->
    <div class="space-y-2">
      <label class="text-p-sm font-medium text-ink-gray-7">Optimisation profile</label>
      <div class="flex flex-wrap gap-2">
        <button
          v-for="p in profiles"
          :key="p.sub_category"
          type="button"
          class="rounded-lg border px-3 py-1.5 text-p-sm transition-colors"
          :class="
            profileName === p.sub_category
              ? 'border-outline-gray-4 bg-surface-gray-2 text-ink-gray-9'
              : 'border-outline-gray-2 text-ink-gray-7 hover:border-outline-gray-3'
          "
          @click="profileName = p.sub_category"
        >
          {{ p.sub_category }}
          <span class="text-ink-gray-5">· 1:{{ p.ram_ratio }}</span>
        </button>
      </div>
    </div>

    <template v-if="profile">
      <!-- vCPU (snaps to steps) -->
      <div class="space-y-2">
        <div class="flex items-baseline justify-between">
          <label class="text-p-sm font-medium text-ink-gray-7">vCPU</label>
          <span class="text-p-sm font-medium text-ink-gray-9">{{ vcpus }} vCPU</span>
        </div>
        <input
          v-model.number="vcpuIndex"
          type="range"
          min="0"
          :max="Math.max(0, maxVcpuIndex)"
          step="1"
          class="w-full accent-ink-gray-9"
        />
        <div class="flex justify-between text-p-xs text-ink-gray-4">
          <span v-for="s in steps" :key="s" :class="{ 'text-ink-gray-7': s === vcpus }">{{ s }}</span>
        </div>
      </div>

      <!-- RAM (follows vCPU automatically) -->
      <div class="flex items-baseline justify-between rounded-lg bg-surface-gray-1 px-3 py-2">
        <span class="text-p-sm text-ink-gray-6">RAM (auto · 1:{{ profile.ram_ratio }})</span>
        <span class="text-p-sm font-medium text-ink-gray-9">{{ ram }} GB</span>
      </div>

      <!-- Disk (independent, bounded) -->
      <div class="space-y-2">
        <div class="flex items-baseline justify-between">
          <label class="text-p-sm font-medium text-ink-gray-7">Disk</label>
          <span class="text-p-sm font-medium text-ink-gray-9">{{ diskGb }} GB</span>
        </div>
        <input
          v-model.number="diskGb"
          type="range"
          :min="profile.disk_min"
          :max="Math.max(profile.disk_min, maxDisk)"
          step="10"
          class="w-full accent-ink-gray-9"
        />
        <div class="flex justify-between text-p-xs text-ink-gray-4">
          <span>{{ profile.disk_min }} GB</span>
          <span>{{ profile.disk_max }} GB</span>
        </div>
      </div>

      <!-- Live estimate -->
      <div class="flex items-center justify-between border-t border-outline-gray-1 pt-4">
        <div>
          <p class="text-p-sm text-ink-gray-6">{{ configSpecs({ sub_category: profileName, vcpus, memory_gb: ram, disk_gb: diskGb }) }}</p>
          <p v-if="overHeadroom" class="text-p-xs text-ink-red-5">
            Over your remaining limit of {{ formatMoney(available, currency) }}.
          </p>
        </div>
        <p class="text-base font-semibold text-ink-gray-9">{{ formatMoney(estimate, currency) }} / mo</p>
      </div>
    </template>
  </div>
</template>
