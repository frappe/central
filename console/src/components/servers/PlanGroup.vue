<script setup lang="ts">
import { computed } from 'vue'
import ConfigDesigner from '@/components/servers/ConfigDesigner.vue'
import { planSpecs, planPrice, formatMoney } from '@/lib/plans'
import { configSpecs, estimateConfig } from '@/lib/composed'
import type { ComposedConfig, Plan, Profile, RateCard } from '@/types/api'

// One optimisation profile's slice of the plan picker: its preset rows plus a
// "Custom" row that designs a config within *this* profile (#84). Used flat (a
// region with no sub-classification) and inside a tab (one per sub-category) — the
// custom designer inherits the profile, so there's no separate profile picker.
const props = defineProps<{
  presets: Plan[]
  profile: Profile | null
  rateCard: RateCard
  available: number
  currency: string
}>()

const selectedPlan = defineModel<string | null>('selectedPlan', { required: true })
const composedConfig = defineModel<ComposedConfig | null>('composedConfig', { required: true })

// A profile-scoped key so the custom selection is distinct per tab.
const customKey = computed(() => (props.profile ? `custom:${props.profile.sub_category}` : ''))
const isCustom = computed(() => !!props.profile && selectedPlan.value === customKey.value)

const customEstimate = computed<number | null>(() =>
  composedConfig.value ? estimateConfig(composedConfig.value, props.rateCard) : null,
)
const customSpec = computed<string>(() =>
  composedConfig.value ? configSpecs(composedConfig.value, props.rateCard.Disk?.unit) : '',
)
const customPrice = computed<string>(() =>
  customEstimate.value !== null ? `${formatMoney(customEstimate.value, props.currency)} / mo` : '',
)

// Bundle-discount note: shown only while the designed shape sits exactly on one of
// this profile's presets (which may price it below its component sum).
const matchingPreset = computed<Plan | null>(() => {
  const c = composedConfig.value
  if (!c || !isCustom.value) return null
  const qty = (p: Plan, t: string) => p.includes.find((i) => i.resource_type === t)?.quantity ?? 0
  return (
    props.presets.find(
      (p) => qty(p, 'Compute') === c.vcpus && qty(p, 'Memory') === c.memory_gb && qty(p, 'Disk') === c.disk_gb,
    ) ?? null
  )
})
</script>

<template>
  <div class="space-y-3">
    <!-- Presets in this profile -->
    <label
      v-for="plan in presets"
      :key="plan.plan"
      class="flex cursor-pointer items-center gap-3 rounded-lg border px-4 py-3 transition-colors"
      :class="
        selectedPlan === plan.plan
          ? 'border-outline-gray-4'
          : 'border-outline-gray-2 hover:border-outline-gray-3'
      "
    >
      <input v-model="selectedPlan" type="radio" :value="plan.plan" class="accent-ink-gray-9" />
      <span class="font-medium text-ink-gray-9">{{ plan.title }}</span>
      <span class="text-p-sm text-ink-gray-5">{{ planSpecs(plan) }}</span>
      <span class="ml-auto font-medium text-ink-gray-9">{{ planPrice(plan) }}</span>
    </label>

    <!-- Custom: a radio row that expands into the design slider for this profile. -->
    <div
      v-if="profile"
      class="rounded-lg border transition-colors"
      :class="isCustom ? 'border-outline-gray-4' : 'border-outline-gray-2 hover:border-outline-gray-3'"
    >
      <label class="flex cursor-pointer items-center gap-3 px-4 py-3">
        <input v-model="selectedPlan" type="radio" :value="customKey" class="accent-ink-gray-9" />
        <span class="font-medium text-ink-gray-9">Custom</span>
        <span class="lucide-sliders-horizontal size-4 text-ink-gray-5" aria-hidden="true" />
        <span v-if="isCustom && customSpec" class="text-p-sm text-ink-gray-5">{{ customSpec }}</span>
        <span class="ml-auto font-medium text-ink-gray-9">{{ isCustom ? customPrice : 'Design your own' }}</span>
      </label>

      <!-- Smooth expand: animate grid rows 0fr → 1fr (CSS only). -->
      <div
        class="grid transition-[grid-template-rows] duration-200 ease-out"
        :class="isCustom ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'"
      >
        <div class="overflow-hidden">
          <div class="border-t border-outline-gray-2 px-4 py-4">
            <ConfigDesigner
              v-if="isCustom"
              :key="profile.sub_category"
              v-model="composedConfig"
              :profiles="[profile]"
              :rate-card="rateCard"
              :available="available"
            />
            <p v-if="matchingPreset" class="mt-3 text-p-xs text-ink-gray-5">
              The <span class="font-medium text-ink-gray-7">{{ matchingPreset.title }}</span> preset offers this
              exact shape — it may be cheaper than building it à la carte.
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
